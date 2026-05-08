from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from utils.timezone import serialize_shanghai_datetime


class ShanghaiBaseModel(BaseModel):
    model_config = ConfigDict(
        json_encoders={datetime: serialize_shanghai_datetime},
    )


class ShanghaiOrmModel(ShanghaiBaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={datetime: serialize_shanghai_datetime},
    )
