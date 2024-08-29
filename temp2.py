def my_callback():
    print("HELOOOOOO from my_callback")
    return 100001


# We want to start the app with the `python -m app.server --mode mock` command
# Before that we want to register a cross-process callback which will be called periodically by the app
# We can't modify the app code


if __name__ == "__main__":
    from temp1 import MyManager

    manager = MyManager(
        address=("localhost", 50000),
        authkey=b"password",
    )
    manager.connect()

    manager.register_callback("my_callback", my_callback)

    # try:
    #     while True:
    #         print(".", end="", flush=True)
    #         time.sleep(1)
    # except KeyboardInterrupt:
    #     pass
