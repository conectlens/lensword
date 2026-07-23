from pydantic import BaseModel, Field

from app.api.schemas.auth import UserResponse


class RecallSettingsResponse(BaseModel):
    enabled: bool
    intensity: int
    morning_checkin_enabled: bool
    idle_time_enabled: bool
    walking_mode_enabled: bool
    walking_steps_threshold: int
    study_breaks_enabled: bool
    study_blocks_before_break: int
    night_winddown_enabled: bool
    night_start_time: str
    night_end_time: str
    push_enabled: bool
    email_enabled: bool
    desktop_enabled: bool
    in_app_enabled: bool
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    # Stored on the user rather than on these settings, but surfaced here:
    # quiet hours are meaningless without the zone they are read in, and this
    # is the screen where they are configured (issue #44).
    time_zone: str


class RecallSettingsUpdateRequest(BaseModel):
    enabled: bool = True
    intensity: int = Field(default=3, ge=1, le=5)
    morning_checkin_enabled: bool = True
    idle_time_enabled: bool = True
    walking_mode_enabled: bool = False
    walking_steps_threshold: int = Field(default=1000, ge=100, le=50000)
    study_breaks_enabled: bool = True
    study_blocks_before_break: int = Field(default=2, ge=1, le=10)
    night_winddown_enabled: bool = False
    night_start_time: str = "22:00"
    night_end_time: str = "23:00"
    push_enabled: bool = True
    email_enabled: bool = False
    desktop_enabled: bool = False
    in_app_enabled: bool = True
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    # Omitted by a client that does not manage zones, which then leaves the
    # stored value untouched rather than resetting it to UTC.
    time_zone: str | None = None


class BadgeResponse(BaseModel):
    code: str
    name: str
    icon: str
    description: str
    earned: bool


class ProfileOverviewResponse(BaseModel):
    user: UserResponse
    badges: list[BadgeResponse]
