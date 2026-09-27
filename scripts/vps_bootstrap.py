#!/usr/bin/env python
"""Первое подключение к VPS по паролю: кладёт ключ деплоя и показывает, что за сервер.

Использование:
    py -3 scripts/vps_bootstrap.py IP ПАРОЛЬ [ПОЛЬЗОВАТЕЛЬ]

После него scripts/deploy_vps.sh ходит на сервер по ключу ~/.ssh/max_campus_vps,
пароль больше не нужен. Требует paramiko (py -3 -m pip install paramiko).
"""

from __future__ import annotations

import sys
from pathlib import Path

import paramiko

KEY = Path.home() / ".ssh" / "max_campus_vps.pub"

CHECKS = {
    "ОС": ". /etc/os-release && echo \"$PRETTY_NAME\"",
    "виртуализация": "systemd-detect-virt 2>/dev/null || echo unknown",
    "память": "free -m | awk '/Mem:/{print $2\" МБ\"}'",
    "подкачка": "free -m | awk '/Swap:/{print $2\" МБ\"}'",
    "диск /": "df -h / | awk 'NR==2{print $2\" всего, \"$4\" свободно\"}'",
    "ядра": "nproc",
    "IPv4 наружу": "curl -4 -s -m 10 https://ifconfig.me || echo нет",
}


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    host, password = sys.argv[1], sys.argv[2]
    user = sys.argv[3] if len(sys.argv) > 3 else "root"
    pub = KEY.read_text(encoding="utf-8").strip()

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=password, timeout=20,
                   allow_agent=False, look_for_keys=False)

    def run(cmd: str) -> str:
        _, out, err = client.exec_command(cmd, timeout=60)
        return (out.read() + err.read()).decode("utf-8", "replace").strip()

    run("mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys "
        f"&& grep -qF '{pub}' ~/.ssh/authorized_keys || echo '{pub}' >> ~/.ssh/authorized_keys; "
        "chmod 600 ~/.ssh/authorized_keys")
    print(f"Ключ деплоя добавлен для {user}@{host}\n")

    for name, cmd in CHECKS.items():
        print(f"  {name:14} {run(cmd)}")

    virt = run("systemd-detect-virt 2>/dev/null || true")
    if virt in {"openvz", "lxc", "lxc-libvirt"}:
        print(f"\n! Виртуализация {virt}: Docker здесь, скорее всего, не заработает.")
    client.close()


if __name__ == "__main__":
    main()
