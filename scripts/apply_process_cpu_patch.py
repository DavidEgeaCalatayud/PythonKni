from pathlib import Path

path = Path("tools/process_manager_tool.py")
text = path.read_text(encoding="utf-8")
old = '''def load_processes_task(worker, cpu_min, mem_min):
    """Collect process metrics outside the Qt GUI thread."""
    processes = []
    for proc in psutil.process_iter(["pid", "name"]):
        worker.check_cancelled()
        try:
            cpu = proc.cpu_percent(interval=0.1)
            mem = proc.memory_percent()
            if cpu < cpu_min and mem < mem_min:
                continue
            processes.append((proc.pid, proc.info["name"] or "Desconocido", cpu, mem))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return processes
'''
new = '''CPU_SAMPLE_SECONDS = 0.1


def load_processes_task(worker, cpu_min, mem_min):
    """Collect process metrics with one shared non-blocking CPU sample window."""
    candidates = []
    for proc in psutil.process_iter(["pid", "name"]):
        worker.check_cancelled()
        try:
            proc.cpu_percent(interval=None)
            candidates.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if candidates:
        if worker.cancel_event.wait(CPU_SAMPLE_SECONDS):
            worker.check_cancelled()

    processes = []
    for proc in candidates:
        worker.check_cancelled()
        try:
            cpu = proc.cpu_percent(interval=None)
            mem = proc.memory_percent()
            if cpu < cpu_min and mem < mem_min:
                continue
            processes.append((proc.pid, proc.info["name"] or "Desconocido", cpu, mem))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return processes
'''
if old not in text:
    raise SystemExit("Expected load_processes_task block was not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
