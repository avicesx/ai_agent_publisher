from pydantic import BaseModel
from typing import List


class GenerateThumbnailsRequest(BaseModel):
    video_path: str
    n_thumbnails: int = 3


class ThumbnailInfo(BaseModel):
    path: str
    frame_idx: int
    score: float


class GenerateThumbnailsResponse(BaseModel):
    thumbnails: List[ThumbnailInfo]
