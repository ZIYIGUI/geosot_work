# -*- coding: utf-8 -*-
"""检查并重启 uvicorn 服务, 然后运行全量黄金测试"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

WORK = r'D:\edgeDownload\geosot_work'
PY = r'D:\pyenv\pyenv-win\versions\3.14.5\python.exe'


def up():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/', timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    # 1) 如果服务没起来, 用后台方式启动
    if not up():
        print('service down, starting...')
        env = dict(os.environ)
        env['PYTHONPATH'] = WORK
        log = open(os.path.join(WORK, 'uvicorn.log'), 'a', encoding='utf-8')
        proc = subprocess.Popen([PY, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', '8000'],
                                cwd=WORK, env=env, stdout=log, stderr=log,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(30):
            time.sleep(1)
            if up():
                print('service up (pid %d)' % proc.pid)
                break
        else:
            print('service FAILED to start, check uvicorn.log')
            sys.exit(1)
    else:
        print('service already up')

    # 2) 全量黄金测试
    import json
    sys.path.insert(0, WORK)
    os.chdir(WORK)
    rc = subprocess.call([PY, 'test_all.py'], cwd=WORK)
    print('test_all rc =', rc)


if __name__ == '__main__':
    main()
