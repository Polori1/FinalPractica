from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import col, select
from dependencies import SessionDep, get_user_or_404
from models import PostPublic, UserPublic, Like, Post, PostPublic, UserPublic

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}", response_model=UserPublic)
def read_user(user_id: int, db: SessionDep):
    return get_user_or_404(db, user_id)


@router.get("/{user_id}/posts", response_model=list[PostPublic])
def read_user_posts(user_id: int, db: SessionDep):
    return get_user_or_404(db, user_id).posts

@router.get("/{user_id}/likes", response_model=list[PostPublic])
def read_user_likes(
    user_id: int, db: SessionDep, offset: int = 0, limit: Annotated[int, Query(le=100)] = 20
):
    # TODO 6 (DESAFÍO, sin pistas de código): es el espejo del TODO 5.
    get_user_or_404(db, user_id)

    stmt = (
        select(Post)
        .join(Like, col(Like.post_id) == col(Post.id))
        .where(col(Like.user_id) == user_id) 
        .order_by(col(Like.created_at).desc()) 
        .offset(offset) 
        .limit(limit)
    )

    return db.exec(stmt).all()