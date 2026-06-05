"""
PRAGNYA API Routes — discipline engine endpoints
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pragnya_engine import (
    get_state, get_today_trades, get_today_violations,
    save_eod_emotion, get_eod_emotion,
    get_total_rewards, get_rewards_history,
    add_reward, get_daily_quote,
)

router = APIRouter()

@router.get("/state/{product}")
async def get_pragnya_state(product: str):
    product = product.upper()
    state   = get_state(product)
    trades  = get_today_trades(product)
    viols   = get_today_violations(product)
    eod     = get_eod_emotion(product)
    quote_text, quote_src = get_daily_quote()
    return {
        "state":      state,
        "trades":     trades,
        "violations": viols,
        "eod":        eod,
        "quote":      {"text": quote_text, "src": quote_src},
        "rewards": {
            "total":   get_total_rewards(),
            "history": get_rewards_history(10),
        },
    }

class EmotionRequest(BaseModel):
    product: str
    emotion: str
    note:    str = ""

@router.post("/emotion")
async def log_emotion(req: EmotionRequest):
    save_eod_emotion(req.product.upper(), req.emotion, req.note)
    add_reward(req.product.upper(), "EMOTION_LOGGED")
    return {"status": "ok"}

@router.get("/rewards")
async def get_rewards():
    return {
        "total":   get_total_rewards(),
        "history": get_rewards_history(30),
        "events":  {
            "NO_REVENGE":      50,
            "TARGET_STOP":     100,
            "FIVE_DAY_STREAK": 500,
            "FULL_RULES":      75,
            "EMOTION_LOGGED":  10,
        }
    }

@router.get("/quote")
async def get_quote():
    text, src = get_daily_quote()
    return {"text": text, "src": src}
