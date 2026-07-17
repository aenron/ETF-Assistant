from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models.user import User
from routers.auth import get_current_user
from schemas.watchlist import WatchlistCreate, WatchlistItemResponse, WatchlistRefreshResponse, WatchlistUpdate
from services.watchlist_service import WatchlistService

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistItemResponse])
async def get_watchlist(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return await WatchlistService.list_items(db, user_id=current_user.id)


@router.post("", response_model=WatchlistItemResponse)
async def create_watchlist_item(
    data: WatchlistCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        return await WatchlistService.create(db, data, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{item_id}", response_model=WatchlistItemResponse)
async def update_watchlist_item(
    item_id: int,
    data: WatchlistUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    result = await WatchlistService.update(db, item_id, data, user_id=current_user.id)
    if not result:
        raise HTTPException(status_code=404, detail="自选项不存在")
    return result


@router.delete("/{item_id}")
async def delete_watchlist_item(
    item_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    success = await WatchlistService.delete(db, item_id, user_id=current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="自选项不存在")
    return {"message": "删除成功"}


@router.post("/refresh-all", response_model=WatchlistRefreshResponse)
async def refresh_watchlist_quotes(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return await WatchlistService.refresh_all(db, user_id=current_user.id)
