import hashlib
import logging
import os
import sqlite3
import time
import urllib.parse
from dataclasses import dataclass
from typing import Dict, List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ----------- Configuration -----------
BOT_TOKEN = os.getenv("BOT_TOKEN", "8915702735:AAF5XIqDqchFbjSmB9gAKCHmdAaNipqKECM")
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "@Tfben10")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "-1003849178352"))
DB_PATH = os.getenv("DB_PATH", "bot.db")

# Addresses are placeholders; replace with your real wallet addresses by network.
WALLET_ADDRESSES: Dict[str, Dict[str, str]] = {
    "USDT": {
        "ETHEREUM": "0xYourUsdtEthAddress",
        "TRON": "TYourUsdtTronAddress",
        "BSC": "0xYourUsdtBscAddress",
        "SOLANA": "YourUsdtSolanaAddress",
        "POLYGON": "0xYourUsdtPolygonAddress",
        "TON": "UQYourUsdtTonAddress",
    },
    "USDC": {
        "ETHEREUM": "0xYourUsdcEthAddress",
        "SOLANA": "YourUsdcSolanaAddress",
        "BSC": "0xYourUsdcBscAddress",
        "POLYGON": "0xYourUsdcPolygonAddress",
        "BASE": "0xYourUsdcBaseAddress",
        "TON": "UQYourUsdcTonAddress",
    },
    "BTC": {"BITCOIN": "bc1YourBtcAddress"},
    "ETH": {
        "ETHEREUM": "0xYourEthAddress",
        "BSC": "0xYourEthBscWrappedAddress",
        "BASE": "0xYourEthBaseAddress",
    },
    "LTC": {"LITECOIN": "ltc1YourLtcAddress"},
    "SOL": {"SOLANA": "YourSolAddress"},
    "TRX": {"TRON": "TYourTronAddress"},
    "XMR": {"MONERO": "44AFFq5kSiGBoZ..."},
    "DAI": {
        "ETHEREUM": "0xYourDaiEthAddress",
        "BSC": "0xYourDaiBscAddress",
        "POLYGON": "0xYourDaiPolygonAddress",
    },
    "DOGE": {"DOGECOIN": "DYourDogeAddress"},
}

CURRENCY_TO_GAME_RATE = {
    "USDT": 1.0,
    "USDC": 1.0,
}


@dataclass
class PendingProof:
    currency: str
    network: str


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            game_balance REAL NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS proofs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            currency TEXT NOT NULL,
            network TEXT NOT NULL,
            proof_hash TEXT NOT NULL UNIQUE,
            proof_text TEXT,
            amount REAL,
            game_credit REAL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action_type TEXT NOT NULL,
            details TEXT,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💰 Deposit", callback_data="menu:deposit")],
            [InlineKeyboardButton("🏧 Withdraw", callback_data="menu:withdraw")],
            [InlineKeyboardButton("✅ Verify Payment", callback_data="menu:verify")],
            [InlineKeyboardButton("👛 Balance", callback_data="menu:balance")],
        ]
    )


def back_keyboard(dest: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=dest)]])


def currencies_keyboard(prefix: str) -> InlineKeyboardMarkup:
    rows = []
    for currency in sorted(WALLET_ADDRESSES.keys()):
        rows.append([InlineKeyboardButton(currency, callback_data=f"{prefix}:currency:{currency}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


def networks_keyboard(prefix: str, currency: str) -> InlineKeyboardMarkup:
    rows = []
    for network in WALLET_ADDRESSES[currency].keys():
        rows.append([InlineKeyboardButton(network, callback_data=f"{prefix}:network:{currency}:{network}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data=f"menu:{prefix}")])
    return InlineKeyboardMarkup(rows)


def address_for(currency: str, network: str) -> str:
    return WALLET_ADDRESSES[currency][network]


def qr_link(address: str) -> str:
    return f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={urllib.parse.quote(address)}"


async def log_action(context: ContextTypes.DEFAULT_TYPE, user_id: int, action_type: str, details: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO actions (user_id, action_type, details, created_at) VALUES (?, ?, ?, ?)",
        (user_id, action_type, details, int(time.time())),
    )
    conn.commit()
    conn.close()

    if LOG_CHANNEL_ID:
        try:
            await context.bot.send_message(
                chat_id=LOG_CHANNEL_ID,
                text=f"📝 <b>{action_type}</b>\nUser: <code>{user_id}</code>\nDetails: {details}",
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            logging.warning("Failed to send log to channel: %s", exc)


def ensure_user(user_id: int, username: str | None) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, created_at) VALUES (?, ?, ?)",
        (user_id, username or "", int(time.time())),
    )
    conn.execute("UPDATE users SET username = ? WHERE user_id = ?", (username or "", user_id))
    conn.commit()
    conn.close()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    ensure_user(user.id, user.username)
    await log_action(context, user.id, "START", f"username=@{user.username or 'unknown'}")
    await update.message.reply_text(
        "Welcome! Use the buttons below to deposit, withdraw, verify payment, and view balance.",
        reply_markup=menu_keyboard(),
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    ensure_user(user.id, user.username)
    data = query.data

    if data == "menu:home":
        await query.edit_message_text("Main menu", reply_markup=menu_keyboard())
        return

    if data == "menu:deposit":
        await query.edit_message_text("Select currency to deposit:", reply_markup=currencies_keyboard("deposit"))
        return

    if data == "menu:withdraw":
        await query.edit_message_text("Select currency to withdraw:", reply_markup=currencies_keyboard("withdraw"))
        return

    if data == "menu:verify":
        await query.edit_message_text(
            "Select currency you deposited, then network, then send proof (tx hash/screenshot text) in next message.",
            reply_markup=currencies_keyboard("verify"),
        )
        return

    if data == "menu:balance":
        conn = get_conn()
        row = conn.execute("SELECT game_balance FROM users WHERE user_id = ?", (user.id,)).fetchone()
        conn.close()
        bal = row["game_balance"] if row else 0
        await query.edit_message_text(f"Your game balance: ${bal:.2f}", reply_markup=back_keyboard("menu:home"))
        return

    parts = data.split(":")
    if len(parts) >= 3 and parts[1] == "currency":
        mode = parts[0]
        currency = parts[2]
        await query.edit_message_text(
            f"Select network for {currency}:", reply_markup=networks_keyboard(mode, currency)
        )
        return

    if len(parts) >= 4 and parts[1] == "network":
        mode, _, currency, network = parts
        if mode == "deposit":
            addr = address_for(currency, network)
            text = (
                f"Deposit <b>{currency}</b> on <b>{network}</b>\n\n"
                f"Address:\n<code>{addr}</code>\n\n"
                f"QR: {qr_link(addr)}"
            )
            await log_action(context, user.id, "DEPOSIT_VIEW", f"{currency}-{network}")
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_keyboard("menu:deposit"))
            return

        if mode == "withdraw":
            await log_action(context, user.id, "WITHDRAW_REQUEST", f"{currency}-{network}")
            await query.edit_message_text(
                f"Withdraw for {currency} on {network}:\nPlease contact owner {OWNER_USERNAME}",
                reply_markup=back_keyboard("menu:withdraw"),
            )
            return

        if mode == "verify":
            context.user_data["pending_proof"] = PendingProof(currency=currency, network=network)
            await query.edit_message_text(
                f"Now send your proof for {currency} on {network}.\n"
                "Example: transaction hash, amount, sender info, or screenshot caption."
                "\n\nYou cannot use the same proof twice.",
                reply_markup=back_keyboard("menu:verify"),
            )
            return


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    ensure_user(user.id, user.username)
    pending = context.user_data.get("pending_proof")
    if not pending:
        await update.message.reply_text("Use /start and choose a menu option.")
        return

    proof = update.message.text.strip()
    proof_hash = hashlib.sha256(proof.encode("utf-8")).hexdigest()
    amount = extract_amount(proof)
    game_credit = convert_to_game_currency(pending.currency, amount)

    conn = get_conn()
    existing = conn.execute("SELECT id FROM proofs WHERE proof_hash = ?", (proof_hash,)).fetchone()
    if existing:
        conn.close()
        await update.message.reply_text("❌ This proof has already been used. Please send a different valid proof.")
        await log_action(context, user.id, "VERIFY_DUPLICATE", f"hash={proof_hash[:12]}")
        return

    conn.execute(
        """
        INSERT INTO proofs (user_id, currency, network, proof_hash, proof_text, amount, game_credit, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user.id, pending.currency, pending.network, proof_hash, proof, amount, game_credit, "APPROVED", int(time.time())),
    )
    conn.execute(
        "UPDATE users SET game_balance = game_balance + ? WHERE user_id = ?",
        (game_credit, user.id),
    )
    conn.commit()
    conn.close()

    context.user_data.pop("pending_proof", None)

    await update.message.reply_text(
        f"✅ Proof accepted for {pending.currency}-{pending.network}.\n"
        f"Detected amount: {amount:.6f}\nGame credit added: ${game_credit:.2f}",
        reply_markup=menu_keyboard(),
    )
    await log_action(
        context,
        user.id,
        "VERIFY_OK",
        f"{pending.currency}-{pending.network} amount={amount} credit={game_credit}",
    )


def extract_amount(text: str) -> float:
    tokens = text.replace(",", " ").split()
    for token in tokens:
        try:
            val = float(token)
            if val > 0:
                return val
        except ValueError:
            continue
    return 0.0


def convert_to_game_currency(currency: str, amount: float) -> float:
    rate = CURRENCY_TO_GAME_RATE.get(currency, 0.0)
    return round(amount * rate, 2)


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Set BOT_TOKEN environment variable")

    logging.basicConfig(level=logging.INFO)
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling()


if __name__ == "__main__":
    main()

