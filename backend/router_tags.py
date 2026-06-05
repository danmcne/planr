# backend/router_tags.py
"""
Tag routes.

  GET    /api/tags            list all tags with object counts
  DELETE /api/tags/{tag_id}   remove a tag from all objects then delete it
"""

from typing import List

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from db import get_db

router = APIRouter(prefix='/tags', tags=['tags'])


class TagResponse(BaseModel):
    id:    str
    name:  str
    count: int    # number of objects currently using this tag


@router.get('/', response_model=List[TagResponse])
async def list_tags(db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute(
        "SELECT t.id, t.name, COUNT(ot.object_id) AS count "
        "FROM tags t LEFT JOIN object_tags ot ON ot.tag_id = t.id "
        "GROUP BY t.id ORDER BY t.name COLLATE NOCASE"
    )
    return [TagResponse(id=r['id'], name=r['name'], count=r['count'])
            for r in await cur.fetchall()]


@router.delete('/{tag_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(tag_id: str, db: aiosqlite.Connection = Depends(get_db)):
    cur = await db.execute("SELECT id FROM tags WHERE id = ?", (tag_id,))
    if not await cur.fetchone():
        raise HTTPException(404, detail='Tag not found')
    # object_tags has ON DELETE CASCADE — junction rows cleaned up automatically
    await db.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    await db.commit()
