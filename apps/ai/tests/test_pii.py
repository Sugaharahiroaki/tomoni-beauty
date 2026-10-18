from apps.ai.pii import check_text, find_forbidden_terms, name_variants


def test_name_variants_splits_surname_and_given_name():
    v = name_variants("山田 花子", "やまだ はなこ", None)
    assert {"山田", "花子", "山田花子", "山田 花子", "やまだ", "はなこ"} <= v


def test_name_variants_ignores_single_char_parts():
    v = name_variants("林 蘭")
    assert "林" not in v and "蘭" not in v
    assert "林蘭" in v


def test_detects_customer_name_and_honorific():
    terms = name_variants("山田 花子", "やまだ はなこ")
    result = check_text("今日は山田さんが色落ちのご相談で来てくれました", terms)
    assert not result.passed
    kinds = {f.kind for f in result.findings}
    assert "customer_name" in kinds
    assert "named_person" in kinds
    # 顧客名そのものは error、「○○さん」の呼びかけは確認を促す warning
    assert {f.kind for f in result.errors} == {"customer_name"}
    assert any(f.kind == "named_person" for f in result.warnings)


def test_unknown_person_with_honorific_is_warning_only():
    result = check_text("先輩の鈴木さんに教わりました", set())
    assert result.passed
    assert [f.kind for f in result.warnings] == ["named_person"]


def test_generic_honorifics_are_not_flagged():
    result = check_text("お客様から色落ちのご相談。初めてさんも大歓迎です。", set())
    assert result.passed
    assert not result.findings


def test_detects_age_phone_email():
    result = check_text("32歳のお客様。連絡先は 090-1234-5678 / mail@example.com", set())
    kinds = {f.kind for f in result.findings}
    assert {"age", "phone", "email"} <= kinds
    assert not result.passed


def test_sensitive_topics_are_warnings_not_errors():
    result = check_text("転職をきっかけにイメチェン", set())
    assert result.passed
    assert result.warnings and result.warnings[0].kind == "sensitive_topic"


def test_find_forbidden_terms_normalizes_width():
    assert find_forbidden_terms("ＹＡＭＡＤＡさん", {"YAMADA"}) == ["YAMADA"]


def test_clean_post_passes():
    text = "「色落ちが早くて毎回すぐ明るくなってしまう」というご相談から、今日は落ち着いたブラウンに。褪色しても赤みが出にくい設計にしました。"
    result = check_text(text, name_variants("山田 花子"))
    assert result.passed
    assert result.to_dict()["passed"] is True
