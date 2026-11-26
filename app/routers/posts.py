from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import col, select, func, select

from dependencies import CurrentUser, SessionDep, get_post_or_404, is_admin, require
from models import Post, PostCreate, PostPublic, PostUpdate, Like, User, UserPublic

router = APIRouter(prefix="/posts", tags=["posts"])


@router.get("", response_model=list[PostPublic])
def read_posts(db: SessionDep, offset: int = 0, limit: Annotated[int, Query(le=100)] = 20):
    stmt = select(Post).order_by(col(Post.created_at).desc()).offset(offset).limit(limit)
    return db.exec(stmt).all()


@router.get("/{post_id}", response_model=PostPublic)
def read_post(post_id: int, db: SessionDep):
    return get_post_or_404(db, post_id)


@router.post("", response_model=PostPublic, status_code=201)
def create_post(data: PostCreate, db: SessionDep, current_user: CurrentUser):
    # TODO 5: el autor sale del TOKEN, no del cuerpo.
    #   (Primero quita author_id de PostCreate en models.py.)
        post = Post(**data.model_dump(), author_id=current_user.id)
    #   → db.add → db.commit → db.refresh → return post
        db.add(post)
        db.commit()
        db.refresh(post)
        return post


@router.patch("/{post_id}", response_model=PostPublic)
def update_post(post_id: int, data: PostUpdate, db: SessionDep, current_user: CurrentUser):
    # TODO 6: solo el autor puede editar (o un admin).
       post = get_post_or_404(db, post_id)
       require(post.author_id == current_user.id or is_admin(current_user))
       post.sqlmodel_update(data.model_dump(exclude_unset=True))
    #   → db.add → db.commit → db.refresh → return post
       db.add(post)
       db.commit()
       db.refresh(post)
       return post


@router.delete("/{post_id}", status_code=204)
def delete_post(post_id: int, db: SessionDep, current_user: CurrentUser):
    # TODO 7: mismas reglas que editar. Borra con db.delete(post) y db.commit().
    post = get_post_or_404(db, post_id)
    require (post.author_id == current_user.id or is_admin(current_user))

    db.delete(post)
    db.commit()

#Funciones Auxiliares
def posts_with_likes(): return (
                select(Post, func.count(col(Like.user_id))) 
                .join(Like, col(Like.post_id) == col(Post.id), isouter=True) 
                .group_by(col(Post.id))
                )
def to_post_with_likes(row) -> PostWithLikes:
        post, likes_count = row
        return PostWithLikes.model_validate(post, update={"likes_count": likes_count})

def get_post_with_likes_or_404(db: Session, post_id: int) -> PostWithLikes:
    row = db.exec(posts_with_likes().where(Post.id == post_id)).first()
    if row is None:
          raise HTTPException(status_code=404, detail="Post no encontrado")
    return to_post_with_likes(row)

@router.get("", response_model=list[PostWithLikes]) 
def read_posts(db: SessionDep, offset: int = 0, limit: Annotated[int, Query(le=100)] = 20): 
    stmt = posts_with_likes().order_by(col(Post.created_at).desc()).offset(offset).limit(limit) 
    rows = db.exec(stmt).all() 
    return [to_post_with_likes(row) for row in rows]

@router.get("/{post\_id}", response_model=PostWithLikes)
def read_post(post_id: int, db: SessionDep):
     return get_post_with_likes_or_404(db, post_id)

@router.put("/{post_id}/like", response_model=PostWithLikes)
def like_post(post_id: int, db: SessionDep, current_user: CurrentUser):
    # TODO 3: dar like. PUT = "déjalo en este estado": hacerlo dos veces NO es un error (idempotente).
        get_post_or_404(db, post_id)
        like = db.get(Like, (current_user.id, post_id))
        if like is None:
              db.add(Like(user_id=current_user.id, post_id=post_id))
              db.commit() 
              return get_post_with_likes_or_404(db, post_id)

@router.delete("/{post_id}/like", response_model=PostWithLikes)
def unlike_post(post_id: int, db: SessionDep, current_user: CurrentUser):
    # TODO 4: quitar like. Misma idea, al revés, y también idempotente.
        get_post_or_404(db, post_id)
        like = db.get(Like, (current_user.id, post_id))
        if like:
             db.delete(like)
             db.commit()
        return get_post_with_likes_or_404(db, post_id)

@router.get("/{post_id}/likes", response_model=list[UserPublic])
def read_post_likes(
    post_id: int, db: SessionDep, offset: int = 0, limit: Annotated[int, Query(le=100)] = 20
):
    # TODO 5: devuelve los USUARIOS que dieron like (no los likes). Es un JOIN:
       get_post_or_404(db, post_id)
       stmt = (
           select(User)
           .join(Like, col(Like.user_id) == col(User.id))
           .where(Like.post_id == post_id)
           .order_by(col(Like.created_at).desc())
           .offset(offset)
           .limit(limit)
       )
       return db.exec(stmt).all()

