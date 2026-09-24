"""사이트 배포 — site/ 저장소에 커밋하고 GitHub 에 push 한다. Actions 가 빌드·배포한다.

사용:  .\\.venv\\Scripts\\python.exe site\\tools\\deploy.py ["커밋 메시지"]
전제:  site/ 가 git 저장소이고 origin 이 GitHub 저장소를 가리킨다 (최초 1회 설정은 site/README.md 배포 절).
"""
import io
import os
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)


def git(*args, check=True):
    r = subprocess.run(["git", "-C", SITE, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 실패:\n{r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not os.path.isdir(os.path.join(SITE, ".git")):
        raise SystemExit("site/ 가 git 저장소가 아닙니다. README 의 배포 절대로 초기화하세요.")
    msg = sys.argv[1] if len(sys.argv) > 1 else f"content: update {datetime.now():%Y-%m-%d %H:%M}"
    git("add", "-A")
    status = git("status", "--porcelain")
    if not status:
        print("변경 없음 — 배포할 것이 없습니다.")
        return 0
    print("커밋할 변경:\n" + status)
    git("commit", "-m", msg)
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    print(git("push", "origin", branch, check=True) or f"pushed {branch}")
    remote = git("remote", "get-url", "origin")
    repo = remote.replace(".git", "").split("github.com")[-1].strip("/:")
    print(f"배포 진행 상황: https://github.com/{repo}/actions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
