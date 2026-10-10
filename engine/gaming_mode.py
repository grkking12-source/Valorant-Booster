"""Gaming Mode state machine. Dependencies are injected so it can be tested without Windows.
Safety: if enabling fails halfway, everything already changed is restored immediately."""


class GamingMode:
    def __init__(self, plan_fn, apply_fn, revert_fn, log=print):
        self.plan_fn, self.apply_fn, self.revert_fn, self.log = plan_fn, apply_fn, revert_fn, log
        self.active = False

    def enable(self):
        if self.active:
            return []
        self.active = True
        try:
            results = self.apply_fn(self.plan_fn())
            for label, outcome in results:
                self.log(f"  {label}: {outcome}")
            return results
        except Exception as e:
            self.log(f"ERROR while enabling ({e}) - restoring everything now")
            self.disable()
            return []

    def disable(self):
        results = self.revert_fn()
        self.active = False
        for _, kind, target, ok, msg in results:
            self.log(f"  {'OK  ' if ok else 'FAIL'} {target}: {msg}")
        if not results:
            self.log("  nothing to restore")
        return results
