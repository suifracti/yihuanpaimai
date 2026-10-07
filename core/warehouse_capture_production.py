"""Closed production composition for post-settlement warehouse capture.

Lazy: constructing the host or factory does not load user32 or send wheels.
Adapters are created only when a confirmed session actually starts.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from warehouse_capture_arming import CONFIRM_CAPTION
from warehouse_wheel_driver import WarehouseWheelDriver, WarehouseWheelContext, issue_warehouse_wheel_session_token
from warehouse_input_abort_guard import WarehouseInputAbortGuard


class ProductionScrollDriverFactory:
    """Builder only. Instantiating this object sends no input."""

    def build(self, *, os_adapter: Any) -> Optional[WarehouseWheelDriver]:
        if os_adapter is None:
            return None
        return WarehouseWheelDriver(os_adapter=os_adapter)


class PulseDownScrollRequester:
    """One downward vertical notch per request. Never clicks, types, or scrolls up."""

    def __init__(self, driver: WarehouseWheelDriver, context_factory: Callable[[], WarehouseWheelContext]):
        self._driver = driver
        self._context_factory = context_factory
        self._input_guard = None
        self.requests = []

    def attach_input_abort_guard(self, guard: Any) -> None:
        self._input_guard = guard
        if hasattr(self._driver, "set_input_guard"):
            try:
                self._driver.set_input_guard(guard)
            except Exception:
                pass

    def request_next_scroll(self) -> None:
        context = self._context_factory()
        if getattr(context, "input_guard", None) is None and self._input_guard is not None:
            context.input_guard = self._input_guard
        began = self._driver.begin(context)
        if not began.get("ok"):
            raise RuntimeError(str(began.get("reason") or "BEGIN_FAILED"))
        try:
            once = self._driver.scroll_once()
            if not once.get("ok"):
                raise RuntimeError(str(once.get("reason") or "SCROLL_FAILED"))
            self.requests.append("DOWN")
        finally:
            self._driver.end()


_PRODUCTION_PLACEMENT_RESOLVER: Optional[Any] = None


def get_production_placement_resolver() -> Any:
    global _PRODUCTION_PLACEMENT_RESOLVER
    if _PRODUCTION_PLACEMENT_RESOLVER is None:
        from warehouse_placement_resolver import WarehousePlacementResolver

        _PRODUCTION_PLACEMENT_RESOLVER = WarehousePlacementResolver()
    return _PRODUCTION_PLACEMENT_RESOLVER


def production_reconstruction_factory(record_stable_key: str, **kwargs) -> Any:
    from warehouse_reconstruction import WarehouseReconstructionProcessor

    return WarehouseReconstructionProcessor(
        record_stable_key,
        placement_resolver=get_production_placement_resolver(),
        **kwargs,
    )


def make_production_session_factory(
    *,
    bindings_probe: Callable[[], Any],
    os_adapter_factory: Callable[[], Any],
    store_factory: Callable[[], Any],
    frame_provider_factory: Optional[Callable[[], Any]] = None,
    scene_validator_factory: Optional[Callable[[], Any]] = None,
    reconstruction_factory: Optional[Callable[..., Any]] = None,
):
    recon_factory = reconstruction_factory or production_reconstruction_factory

    def factory(
        *,
        scene,
        cancellation_token,
        status_sink,
        settlement_entered_monotonic: Optional[float] = None,
        game_remaining_s: Optional[float] = None,
        deadline_monotonic: Optional[float] = None,
        **kwargs,
    ):
        from warehouse_capture_session import WarehouseCaptureSession

        adapter = os_adapter_factory()
        driver = WarehouseWheelDriver(os_adapter=adapter)

        def context_factory():
            snap = bindings_probe() or {}
            key = str(snap.get("recordStableKey") or "")
            hwnd = int(snap.get("hwnd") or 0)
            roi = snap.get("warehouseRoi")
            return WarehouseWheelContext(
                session_token=issue_warehouse_wheel_session_token(),
                record_stable_key=key,
                expected_stable_key=key,
                hwnd=hwnd,
                tracked_hwnd=hwnd,
                settlement_stable=bool(snap.get("isSettlement") and snap.get("stable")),
                warehouse_roi=tuple(roi) if roi else None,
                cancellation_token=cancellation_token,
            )

        requester = PulseDownScrollRequester(driver, context_factory)
        store = store_factory() if store_factory is not None else None
        frames = frame_provider_factory() if frame_provider_factory is not None else None
        validator = scene_validator_factory() if scene_validator_factory is not None else (lambda _raw: scene)
        return WarehouseCaptureSession(
            frame_provider=frames,
            scene_validator=validator,
            scroll_requester=requester,
            cancellation_token=cancellation_token,
            status_sink=status_sink,
            store=store,
            reconstruction_factory=recon_factory,
            settlement_entered_monotonic=settlement_entered_monotonic,
            game_remaining_s=game_remaining_s,
            deadline_monotonic=deadline_monotonic,
            top_support_attempts=2,
        )

    return factory


def make_production_guard_factory(*, adapter_factory: Callable[[], Any]):
    def factory(cancel_token=None, **_kwargs):
        adapter = adapter_factory()
        return WarehouseInputAbortGuard(adapter=adapter, cancel_token=cancel_token)

    return factory


PRODUCTION_CONFIRM_CAPTION = CONFIRM_CAPTION
