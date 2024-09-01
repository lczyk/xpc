import pickle

from xpc import Manager


def test_start() -> None:
    man = Manager()
    man.start()


def test_picklable() -> None:
    man1 = Manager(picklable=True)
    man2 = pickle.loads(pickle.dumps(man1))

    print(man1)
    print(man2)
