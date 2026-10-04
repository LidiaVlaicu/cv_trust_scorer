from bronze.rules.cv_analysis import categorize_skill


def test_exact_lowercase_match():
    assert categorize_skill("python") == "language"


def test_case_insensitive_match():
    assert categorize_skill("Python") == "language"
    assert categorize_skill("PYTHON") == "language"


def test_strips_whitespace():
    assert categorize_skill("  Docker  ") == "devops"


def test_database_category():
    assert categorize_skill("PostgreSQL") == "database"
    assert categorize_skill("postgres") == "database"


def test_bi_analytics_category():
    assert categorize_skill("Power BI") == "bi_analytics"
    assert categorize_skill("Excel") == "bi_analytics"


def test_ml_ai_category():
    assert categorize_skill("LangChain") == "ml_ai"
    assert categorize_skill("scikit-learn") == "ml_ai"


def test_unknown_skill_falls_back_to_other():
    assert categorize_skill("Underwater Basket Weaving") == "other"


def test_ab_testing_is_a_practice():
    assert categorize_skill("A/B Testing") == "practices"
