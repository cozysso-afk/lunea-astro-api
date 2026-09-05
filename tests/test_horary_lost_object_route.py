import astro_core as core
import horary_topic_routes_v3  # noqa: F401


def test_lost_object_uses_movable_possession_second_house():
    spec = core.HORARY_TOPIC_SPECS["lost_object"]
    assert spec["quesited_house"] == 2
    assert spec["event_house"] is None
    assert "분실물" in spec["label_ko"]
    assert "성사각 부재" in spec["note"]
