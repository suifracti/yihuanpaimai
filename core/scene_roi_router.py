"""One scene ROI group per observation; input hints never certify a scene."""
from collections import deque
import json
import time
from pathlib import Path
import cv2
import numpy as np
from roi_scaler import ROIScaler
from visual_catalog import asset_root


class SceneRoiRouter:
    def __init__(self, groups, matcher, *, clock=time.monotonic, confirmations=2, max_fast_retries=2):
        self.groups = tuple(groups)
        self.matcher = matcher
        self.clock = clock
        self.confirmations = confirmations
        self.max_fast_retries = max_fast_retries
        self.confirmed = 'UNKNOWN'
        self.generation = 0
        self._queue = deque(self.groups)
        self._candidate = None
        self._hits = 0
        self._lost_at = clock()
        self._last_frame = None
        self._last_result = None
        self._confirmed_miss_streak = 0

    def hint(self, candidates):
        # Hints reprioritize existing work, they never remove fallback groups.
        ordered = [s for s in candidates if s in self.groups]
        self._queue = deque(dict.fromkeys(ordered + list(self._queue) + list(self.groups)))

    def observe(self, frame):
        # Early warehouse and normal processing share exactly one observation.
        if frame is self._last_frame:
            return dict(self._last_result)
        self._last_frame = frame
        if not self._queue:
            self._queue.extend(self.groups)
        active = self._queue.popleft()
        started = self.clock()
        score, hit = self.matcher(active, frame)
        if hit:
            self._hits = self._hits + 1 if self._candidate == active else 1
            self._candidate = active
            self._queue.appendleft(active)
            if active == self.confirmed:
                self._confirmed_miss_streak = 0
            if self._hits >= self.confirmations:
                if self.confirmed != active:
                    self.generation += 1
                self.confirmed = active
                self._lost_at = None
                self._confirmed_miss_streak = 0
        else:
            self._candidate, self._hits = None, 0
            if self._lost_at is None:
                self._lost_at = self.clock()
                self.generation += 1
            self._queue.append(active)
            # Check likely exits first, then resume the bounded full search.
            if self.confirmed == active:
                self._confirmed_miss_streak += 1
                following = {
                    'TOOL_REPLENISH':['TOOL_REPLENISH_CONFIRM','AUCTION_LOBBY'],
                    'TOOL_REPLENISH_CONFIRM':['TOOL_REPLENISH','AUCTION_LOBBY'],
                    'AUCTION_LOBBY':['TOOL_REPLENISH','AUCTION_LOADING','HELPER_SELECTION'],
                    'SETTLEMENT':['AUCTION_LOADING','AUCTION_LOBBY','OPEN_WORLD'],
                    'AUCTION_LOADING':['IN_AUCTION','AUCTION_LOBBY','OPEN_WORLD'],
                    'IN_AUCTION':['SETTLEMENT','AUCTION_LOADING','OPEN_WORLD'],
                }.get(active,[])
                if self._confirmed_miss_streak <= self.max_fast_retries:
                    # Bounded fast retry: test primary exit, then active, then remaining exits
                    candidates = ([following[0], active] + following[1:]) if following else [active]
                    self.hint(candidates)
                else:
                    # Fast retry budget exhausted: do NOT re-queue active ahead; test exits then all groups
                    self.hint(following)
        ready = hit and self._hits >= self.confirmations
        result = {'scene': self.confirmed if ready else 'UNKNOWN',
                  'lastConfirmedScene': self.confirmed, 'activeGroup':active,
                  'generation':self.generation, 'confirmed':bool(ready),
                  'score':round(float(score),4),
                  'searching':not ready,
                  'message':'未定位，请返回大世界或已支持页面' if self._lost_at is not None and self.clock()-self._lost_at >= 5 else '',
                  'elapsedMs':round((self.clock()-started)*1000,2)}
        if ready:
            result['phase'] = getattr(self.matcher,'phase',None)
        self._last_result = result
        return dict(result)


class TemplateGroupMatcher:
    def __init__(self, directory=None):
        self.directory = Path(directory or asset_root()/'assets/scene_anchors/keyboard')
        self.groups = json.loads((self.directory/'groups.json').read_text(encoding='utf-8'))['groups']
        self.templates = {}
        for group in self.groups.values():
            for anchor in group['anchors'] + group.get('phaseAnchors',[]):
                self.templates[anchor['image']] = cv2.imdecode(np.fromfile(self.directory/anchor['image'],np.uint8),1)

    @staticmethod
    def prepare(image, mode):
        if mode == 'edges':
            return cv2.Canny(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),80,160)
        if mode == 'white':
            hsv = cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
            return cv2.inRange(hsv,(0,0,165),(179,75,255))
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    def __call__(self, scene, frame):
        self.phase = None
        if frame is None or frame.size == 0:
            return 0., False
        h,w = frame.shape[:2]
        vx,vy,vw,vh = ROIScaler.get_viewport_rect(w,h)
        scores = []
        primary=self.groups[scene]['anchors']
        for anchor in primary + self.groups[scene].get('phaseAnchors',[]):
            x1,y1,x2,y2 = anchor['rect']
            padding = self.groups[scene].get('padding',8)
            left,top,right,bottom = max(0,x1-padding),max(0,y1-padding),min(1920,x2+padding),min(1080,y2+padding)
            crop = frame[round(vy+top*vh/1080):round(vy+bottom*vh/1080),round(vx+left*vw/1920):round(vx+right*vw/1920)]
            template = self.templates[anchor['image']]
            if crop.size == 0 or template is None:
                return 0.,False
            resized = cv2.resize(crop,(right-left,bottom-top))
            mode = anchor.get('mode','gray')
            a,b = self.prepare(resized,mode),self.prepare(template,mode)
            score = float(cv2.minMaxLoc(cv2.matchTemplate(a,b,cv2.TM_CCOEFF_NORMED))[1])
            if anchor in primary:
                scores.append(score if np.isfinite(score) else 0.)
            elif score >= anchor.get('threshold',.86):
                self.phase=anchor['phase']
        score = min(scores) if scores else 0.
        return score, score >= self.groups[scene].get('threshold',.83)


def create_keyboard_router():
    matcher = TemplateGroupMatcher()
    return SceneRoiRouter(matcher.groups, matcher)
