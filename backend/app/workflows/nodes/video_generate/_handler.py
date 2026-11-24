"""`video.generate`: the shared media handler, bound to a video request.

Image and video generation share admission, inspection, retention and receipts in
`_media_handler`; this package owns only which kind it asks for.
"""

from functools import partial

from app.workflows.nodes import _media_handler

handle = partial(_media_handler.handle, kind="video")
check_resources = partial(_media_handler.check_resources, kind="video")
available = partial(_media_handler.available, "video")
