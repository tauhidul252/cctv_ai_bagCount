import datetime
from typing import Optional

class NVRStreamHelper:
    """
    Helper to construct and format Live and Playback RTSP Stream URLs
    for major NVR/DVR manufacturers (Hikvision, Dahua, Uniview, CP-Plus, Generic).
    """

    @staticmethod
    def build_live_url(
        brand: str,
        host: str,
        port: int = 554,
        username: str = "admin",
        password: str = "12345",
        channel: int = 1,
        stream_type: str = "main"  # "main" (high res) or "sub" (low res/fluent)
    ) -> str:
        brand = brand.lower().strip()
        auth = f"{username}:{password}@" if username and password else ""
        
        if brand in ("hikvision", "cp_plus", "uniview"):
            # Stream 1 = main, 2 = sub
            stream_id = 1 if stream_type == "main" else 2
            channel_code = f"{channel}0{stream_id}"
            return f"rtsp://{auth}{host}:{port}/Streaming/Channels/{channel_code}"

        elif brand in ("dahua", "imou"):
            subtype = 0 if stream_type == "main" else 1
            return f"rtsp://{auth}{host}:{port}/cam/realmonitor?channel={channel}&subtype={subtype}"

        else:
            # Generic RTSP default
            stream_id = 1 if stream_type == "main" else 2
            return f"rtsp://{auth}{host}:{port}/h264/ch{channel}/{stream_type}/av_stream"

    @staticmethod
    def build_playback_url(
        brand: str,
        host: str,
        port: int = 554,
        username: str = "admin",
        password: str = "12345",
        channel: int = 1,
        start_time: Optional[datetime.datetime] = None,
        end_time: Optional[datetime.datetime] = None
    ) -> str:
        """
        Constructs RTSP playback URL with timestamp query for NVR / DVR archive review.
        """
        brand = brand.lower().strip()
        auth = f"{username}:{password}@" if username and password else ""

        if not start_time:
            start_time = datetime.datetime.now() - datetime.timedelta(hours=1)
        if not end_time:
            end_time = datetime.datetime.now()

        if brand in ("hikvision", "uniview"):
            # Format: YYYYMMDDTHHMMSSZ e.g. 20261022T080000Z
            st_str = start_time.strftime("%Y%m%dT%H%M%SZ")
            et_str = end_time.strftime("%Y%m%dT%H%M%SZ")
            track_id = f"{channel}01"
            return f"rtsp://{auth}{host}:{port}/Streaming/tracks/{track_id}/?starttime={st_str}&endtime={et_str}"

        elif brand in ("dahua", "imou"):
            # Format: YYYY_MM_DD_HH_MM_SS
            st_str = start_time.strftime("%Y_%m_%d_%H_%M_%S")
            et_str = end_time.strftime("%Y_%m_%d_%H_%M_%S")
            return f"rtsp://{auth}{host}:{port}/cam/playback?channel={channel}&subtype=0&starttime={st_str}&endtime={et_str}"

        else:
            # Fallback
            st_str = start_time.strftime("%Y%m%d%H%M%S")
            et_str = end_time.strftime("%Y%m%d%H%M%S")
            return f"rtsp://{auth}{host}:{port}/playback?channel={channel}&start={st_str}&end={et_str}"
