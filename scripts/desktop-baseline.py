#!/usr/bin/env python3
"""Measure the desktop shell against the ADR 0001 Phase 3.1 gates (issue #65).

This script does not make the measurements true — it makes them *reproducible*.
Whoever runs it on a signed build gets the same numbers in the same shape, on
every platform, rather than a figure someone typed into a document once.

Why a script at all, when the numbers are the deliverable? Because the gate is
not "someone measured it in July"; it is a bar the app has to keep clearing.
A measurement nobody can repeat is a claim, not a baseline.

WHAT THIS SCRIPT CANNOT DO
--------------------------
It cannot sign anything, and it refuses to pretend otherwise. ADR 0001 requires
the figures to come from **signed release builds**, because notarisation and
code-signing change startup time — Gatekeeper and SmartScreen both add work on
first launch, and an unsigned measurement flatters the result. Run against an
unsigned build it still works, and labels every figure `unsigned:
NOT-THE-GATE`, because a provisional number that reads like a gate number is
worse than no number.

It also cannot do the packaged-app smoke test ADR 0001 lists — nested-route
relaunch, keyboard navigation, the review flow, room drag-and-drop, the mind
map. Those need a person looking at a screen. They are printed as a checklist
rather than silently dropped.

USAGE
-----
    python3 scripts/desktop-baseline.py --app <path-to-app> [--signed]
    python3 scripts/desktop-baseline.py --app <path> --soak-hours 8

Writes JSON to stdout and a human summary to stderr, so the numbers can be
piped into a file while a person watches the run.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# From ADR 0001, "Performance and release gates". Kept here as data rather than
# prose so a run can say pass or fail rather than leaving the reader to compare
# a number against a document they have to find.
GATES = {
    "warm_startup_median_s": 2.0,
    "warm_startup_p95_s": 3.0,
    "idle_memory_mib": 150.0,
    "idle_memory_with_sidecar_mib": 300.0,
    "idle_cpu_p95_percent": 1.0,
    "soak_memory_growth_percent": 10.0,
}

COLD_LAUNCHES = 5
WARM_LAUNCHES = 20
LAUNCH_QUIT_CYCLES = 20
# ADR 0001 requires no child or sidecar processes remain after this long.
LEFTOVER_GRACE_SECONDS = 5
# How long to wait for the app to fork its webview helpers before giving up on
# that readiness signal. Short: an app that never forks must not silently turn
# this bound into its reported startup time.
READINESS_TIMEOUT_S = 2.0
IDLE_SETTLE_SECONDS = 60
CPU_SAMPLE_MINUTES = 10

# Checks that need a human. Listed rather than skipped silently: a report that
# omits them reads as if everything was covered.
MANUAL_SMOKE_CHECKS = (
    "Relaunch into a nested route (e.g. /groups/1/practice) and land there",
    "Navigate the whole review flow by keyboard only",
    "Sign in, sign out, and sign in again",
    "Trigger an API error (stop the backend) and see a handled message",
    "Complete a review session end to end",
    "Drag and drop a word in a room and see it persist",
    "Open the mind map and expand a node",
    "Observe a native notification toast with its actions",
)


@dataclass
class Measurement:
    """One measured quantity, with its gate and whether it cleared."""

    name: str
    value: float | None
    unit: str
    gate: float | None = None
    passed: bool | None = None
    note: str = ""


@dataclass
class Report:
    platform: str
    app: str
    signed: bool
    # Repeated on every figure below as well. Someone reading one line out of
    # context still has to see it.
    trust: str = ""
    measurements: list[Measurement] = field(default_factory=list)
    manual_checks: list[str] = field(default_factory=lambda: list(MANUAL_SMOKE_CHECKS))
    notes: list[str] = field(default_factory=list)


def _proc_tree_rss_mib(pid: int) -> float | None:
    """Resident memory of a process *and its children*, in MiB.

    The tree, not the process. A webview app's memory lives mostly in helper
    processes, and reporting only the parent would understate it by most of the
    total — which is exactly the flattering-number failure ADR 0001 warns
    against.
    """
    if not shutil.which("ps"):
        return None
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,rss="], capture_output=True, text=True, check=True
        ).stdout
    except subprocess.SubprocessError:
        return None

    children: dict[int, list[int]] = {}
    rss: dict[int, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        try:
            this, parent, kb = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            continue
        children.setdefault(parent, []).append(this)
        rss[this] = kb

    total, stack = 0, [pid]
    seen = set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        total += rss.get(current, 0)
        stack.extend(children.get(current, []))
    return round(total / 1024, 1)


def _descendants(pid: int) -> list[int]:
    if not shutil.which("pgrep"):
        return []
    try:
        out = subprocess.run(
            ["pgrep", "-P", str(pid)], capture_output=True, text=True
        ).stdout
    except subprocess.SubprocessError:
        return []
    return [int(line) for line in out.split() if line.isdigit()]


def _launch(app: str) -> subprocess.Popen:
    return subprocess.Popen(
        [app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
    )


def measure_startup(app: str, count: int, label: str) -> Measurement | list[Measurement]:
    """Time from exec to the process being up.

    Deliberately *not* called "time to first paint". This measures process
    start, which is a floor rather than the number ADR 0001 actually wants —
    the honest thing is to say so rather than relabel it. A real
    time-to-interactive needs the shell to emit a mark the script can wait for,
    which is noted in the report as outstanding work.
    """
    samples = []
    saw_children = False
    for _ in range(count):
        started = time.perf_counter()
        process = _launch(app)
        # A webview app forks helper processes as it comes up, so the first
        # child appearing is the cheapest readiness signal available without
        # instrumenting the app.
        #
        # Bounded tightly, and this bound matters: an app that never forks
        # would otherwise hold the loop for the whole timeout and report a
        # startup time that is really just the timeout. Found by running this
        # against a process with no children — it reported 30s per sample with
        # a straight face. If the signal does not arrive, the sample is still
        # taken and the report says the signal was missing rather than
        # implying the number means what it usually does.
        while process.poll() is None and time.perf_counter() - started < READINESS_TIMEOUT_S:
            if _descendants(process.pid):
                saw_children = True
                break
            time.sleep(0.01)
        samples.append(time.perf_counter() - started)
        _quit(process)

    if not samples:
        return []
    missing_signal = (
        ""
        if saw_children
        else " — NO child-process signal seen; this is a settle time, not a "
        "startup time"
    )
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return [
        Measurement(
            name=f"{label}_startup_median_s",
            value=round(statistics.median(samples), 3),
            unit="s",
            gate=GATES.get(f"{label}_startup_median_s"),
            note="process start, not time-to-interactive — see report notes" + missing_signal,
        ),
        Measurement(
            name=f"{label}_startup_p95_s",
            value=round(p95, 3),
            unit="s",
            gate=GATES.get(f"{label}_startup_p95_s"),
            note=missing_signal.lstrip(' —').strip(),
        ),
    ]


def _quit(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def measure_idle_memory(app: str) -> Measurement:
    process = _launch(app)
    time.sleep(IDLE_SETTLE_SECONDS)
    value = _proc_tree_rss_mib(process.pid)
    _quit(process)
    return Measurement(
        name="idle_memory_mib",
        value=value,
        unit="MiB",
        gate=GATES["idle_memory_mib"],
        note="whole process tree, including webview helpers",
    )


def measure_leftovers(app: str, cycles: int) -> Measurement:
    """Launch and quit repeatedly, then look for survivors.

    The gate ADR 0001 sets is zero, and zero is the only interesting answer:
    one leftover helper per launch is what turns a tray app into something
    people notice in Activity Monitor and uninstall.
    """
    leftover = 0
    for _ in range(cycles):
        process = _launch(app)
        time.sleep(1.5)
        children = _descendants(process.pid)
        _quit(process)
        time.sleep(LEFTOVER_GRACE_SECONDS)
        for child in children:
            try:
                subprocess.run(["kill", "-0", str(child)], capture_output=True, check=True)
                leftover += 1
            except subprocess.CalledProcessError:
                pass
    return Measurement(
        name="leftover_processes",
        value=float(leftover),
        unit="processes",
        gate=0.0,
        note=f"after {cycles} launch/quit cycles, {LEFTOVER_GRACE_SECONDS}s grace",
    )


def measure_installer_sizes(directory: Path) -> list[Measurement]:
    """Record installer size per artefact, separately.

    ADR 0001 asks for shell and bundled-backend costs reported apart. This
    reports what it can see: a bundle's total. Splitting shell from sidecar
    needs the packaging config to say which is which, and inventing a split
    would be worse than admitting the number is combined.
    """
    if not directory.exists():
        return []
    out = []
    for pattern in ("*.dmg", "*.exe", "*.msi", "*.AppImage", "*.deb"):
        for artefact in sorted(directory.rglob(pattern)):
            out.append(
                Measurement(
                    name=f"installer_size_{artefact.suffix.lstrip('.')}",
                    value=round(artefact.stat().st_size / (1024 * 1024), 1),
                    unit="MiB",
                    note=f"{artefact.name} — combined shell and any bundled backend",
                )
            )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, help="Executable inside the packaged build")
    parser.add_argument(
        "--signed",
        action="store_true",
        help="Assert this build is signed. Without it every figure is labelled NOT-THE-GATE.",
    )
    parser.add_argument("--bundles", default="desktop/src-tauri/target/release/bundle")
    parser.add_argument("--quick", action="store_true", help="Fewer samples, for wiring checks")
    args = parser.parse_args()

    app = Path(args.app)
    if not app.exists():
        print(f"No such app: {app}", file=sys.stderr)
        return 2

    report = Report(
        platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
        app=str(app),
        signed=args.signed,
        trust=(
            "signed build — figures count toward the ADR 0001 gate"
            if args.signed
            else "unsigned build — NOT-THE-GATE. Signing and notarisation change "
            "startup time; these figures flatter the result and must not be "
            "recorded as the baseline."
        ),
    )

    warm = WARM_LAUNCHES if not args.quick else 3
    cold = COLD_LAUNCHES if not args.quick else 1
    cycles = LAUNCH_QUIT_CYCLES if not args.quick else 2

    print(f"Measuring {app} ({report.trust})", file=sys.stderr)

    report.measurements.extend(measure_startup(str(app), cold, "cold"))
    report.measurements.extend(measure_startup(str(app), warm, "warm"))
    if not args.quick:
        report.measurements.append(measure_idle_memory(str(app)))
    report.measurements.append(measure_leftovers(str(app), cycles))
    report.measurements.extend(measure_installer_sizes(Path(args.bundles)))

    for measurement in report.measurements:
        if measurement.gate is not None and measurement.value is not None:
            measurement.passed = measurement.value <= measurement.gate
        if not args.signed:
            measurement.note = (measurement.note + " [unsigned: NOT-THE-GATE]").strip()

    report.notes = [
        "Startup here is process start, not time-to-interactive. Closing that "
        "gap needs the shell to emit a mark the harness can wait for; until it "
        "does, treat these as a floor.",
        f"Idle CPU p95 over {CPU_SAMPLE_MINUTES} minutes and the 8-hour tray "
        "soak are not automated here — both need a long-running observer, and "
        "a harness that silently skipped them would report a clean run.",
        "The packaged-app smoke checks below need a person. They are listed so "
        "a report cannot look complete without them.",
    ]
    if not args.signed:
        report.notes.insert(0, "UNSIGNED RUN — no figure here satisfies ADR 0001 Phase 3.1.")

    print(json.dumps(asdict(report), indent=2))

    failures = [m for m in report.measurements if m.passed is False]
    print(
        f"\n{len(report.measurements)} measurement(s), {len(failures)} over gate.",
        file=sys.stderr,
    )
    for check in report.manual_checks:
        print(f"  [ ] {check}", file=sys.stderr)

    # An unsigned run is never a pass, however good the numbers look.
    return 1 if failures or not args.signed else 0


if __name__ == "__main__":
    raise SystemExit(main())
