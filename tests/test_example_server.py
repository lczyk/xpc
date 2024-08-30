import signal
import subprocess


def test_run_server(server: subprocess.Popen) -> None:
    # Send a signal to the server to stop
    server.send_signal(signal.SIGINT)
    retcode = server.wait()
    assert retcode == 0


def test_run_server_again(server: subprocess.Popen) -> None:
    server.send_signal(signal.SIGINT)
    retcode = server.wait()
    assert retcode == 0


def test_run_server_nostop(server: subprocess.Popen) -> None:
    pass


def test_run_server_nostop_again(server: subprocess.Popen) -> None:
    pass
