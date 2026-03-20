"""POST /api/orders — Place and cancel orders."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.models import OrderRequest, OrderType, Side
from dashboard.deps import get_broker

router = APIRouter(tags=["orders"])


class BuyRequest(BaseModel):
    ticker: str
    quantity: float | None = None
    target_value: float | None = None
    limit_price: float | None = None


class SellRequest(BaseModel):
    ticker: str
    quantity: float | None = None
    limit_price: float | None = None


class StopLossRequest(BaseModel):
    ticker: str
    quantity: float
    stop_price: float


@router.post("/orders/buy")
async def place_buy(req: BuyRequest):
    """Place a buy order (market or limit)."""
    broker = get_broker()
    if not broker:
        raise HTTPException(503, "Broker not configured")

    order_type = OrderType.LIMIT if req.limit_price else OrderType.MARKET
    order = OrderRequest(
        ticker=req.ticker.upper(),
        side=Side.BUY,
        order_type=order_type,
        quantity=req.quantity or 0.0,
        target_value=req.target_value,
        limit_price=req.limit_price,
    )
    result = await broker.place_order(order)
    if not result.success:
        raise HTTPException(400, result.error_message)
    return result.model_dump()


@router.post("/orders/sell")
async def place_sell(req: SellRequest):
    """Place a sell order (market or limit)."""
    broker = get_broker()
    if not broker:
        raise HTTPException(503, "Broker not configured")

    order_type = OrderType.LIMIT if req.limit_price else OrderType.MARKET
    order = OrderRequest(
        ticker=req.ticker.upper(),
        side=Side.SELL,
        order_type=order_type,
        quantity=req.quantity or 0.0,
        limit_price=req.limit_price,
    )
    result = await broker.place_order(order)
    if not result.success:
        raise HTTPException(400, result.error_message)
    return result.model_dump()


@router.post("/orders/stoploss")
async def place_stop_loss(req: StopLossRequest):
    """Set a stop-loss order."""
    broker = get_broker()
    if not broker:
        raise HTTPException(503, "Broker not configured")

    order = OrderRequest(
        ticker=req.ticker.upper(),
        side=Side.SELL,
        order_type=OrderType.STOP,
        quantity=req.quantity,
        stop_price=req.stop_price,
    )
    result = await broker.place_order(order)
    if not result.success:
        raise HTTPException(400, result.error_message)
    return result.model_dump()


@router.delete("/orders/{order_id}")
async def cancel_order(order_id: str):
    """Cancel a pending order."""
    broker = get_broker()
    if not broker:
        raise HTTPException(503, "Broker not configured")

    success = await broker.cancel_order(order_id)
    if not success:
        raise HTTPException(400, f"Failed to cancel order {order_id}")
    return {"cancelled": True, "order_id": order_id}


@router.get("/orders/pending")
async def get_pending_orders():
    """Get all pending orders."""
    broker = get_broker()
    if not broker:
        raise HTTPException(503, "Broker not configured")
    return await broker.get_pending_orders()
