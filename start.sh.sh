#!/bin/bash
# Start WhatsApp OTP bridge in background
node whatsapp_otp.js &
# Start Python Telegram bot
python3 bot.py