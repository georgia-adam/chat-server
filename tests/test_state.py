from chat_server.state import load_state, save_state


def test_missing_file_is_empty(tmp_path):
    assert load_state(str(tmp_path / "nope.json")) == {}


def test_round_trip_and_no_tmp_left_behind(tmp_path):
    path = tmp_path / "state.json"
    data = {"last_room": {"a": "b"}, "room_history": {"b": ["a: hi\n"]}}
    save_state(str(path), data)
    assert load_state(str(path)) == data
    assert list(tmp_path.iterdir()) == [path]
