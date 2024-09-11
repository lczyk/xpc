# xpc

[![test](https://github.com/MarcinKonowalczyk/xpc/actions/workflows/test.yml/badge.svg)](https://github.com/MarcinKonowalczyk/xpc/actions/workflows/test.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![Static Badge](https://img.shields.io/badge/python-3.9%20~%203.13-blue)

Cross-process call library for Python.

Inspired by https://gist.github.com/psobot/2690045

Tested in Python 3.9+.

## Usage

This module provides a simple way to register callbacks in one process and call them in another. The motivating
use-case is to allow registering custom callbacks in an application during testing, or for dynamic instrumentation
(although the performance hit might be significant).

In a main application we want to create a Manager object and start it:

```python
from xpc import Manager
man = Manager(
    address=("localhost", 50000),
    authkey="password",
)
man.start()
```

We can then attempt callbacks from it:

```python
result, found = manager.call("my_callback", 1, 2, 3, a=4, b=5)
if found:
    print(f"Result: {result}")
else:
    print("Callback not found")
```

In a separate process, we can register callbacks by creating a Manager object and connecting to the server:

```python
from xpc import Manager

manager = Manager(
    address=("localhost", 50000),
    authkey="password",
)
manager.connect()

def my_callback(*args, **kwargs):
    print("my_callback args:", args, "kwargs:", kwargs)
    return 99

manager.register("my_callback", my_callback)
```

The main app will then succeed in calling the callback. All the `args` and `kwargs` are pickled and sent over to the
process which registered the callback, and the return values are sent back. **The callback executes in the process
which registered it.**

## Install

Just copy the single-module file to your project and import it.

```bash
cp ./src/xpc/xpc.py src/your_package/_xpc.py
```

Or even better, without checking out the repository:

```bash
curl https://raw.githubusercontent.com/MarcinKonowalczyk/xpc/main/src/xpc/xpc.py > src/your_package/_xpc.py
```

Note that like this *you take ownership of the code* and you are responsible for keeping it up-to-date. If you change it that's fine (keep the license pls). That's the point here. You can also copy the code to your project and modify it as you wish.

If you want you can also build and install it as a package, but then the source lives somewhere else. That might be what you want though. 🤷‍♀️

```bash
pip install flit
flit build
ls dist/*
pip install dist/*.whl
```
