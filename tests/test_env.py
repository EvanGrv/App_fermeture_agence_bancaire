from backend.env import load_dotenv


def test_load_dotenv_charge_valeurs(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ANTHROPIC_API_KEY='sk-test'\n"
        'OPENAI_API_KEY="sk-openai"\n'
        "export LEGIFRANCE_CLIENT_ID=abc\n",
        encoding="utf-8",
    )
    env = {}

    load_dotenv(env_file, env=env)

    assert env["ANTHROPIC_API_KEY"] == "sk-test"
    assert env["OPENAI_API_KEY"] == "sk-openai"
    assert env["LEGIFRANCE_CLIENT_ID"] == "abc"


def test_load_dotenv_necrase_pas_par_defaut(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=nouvelle\n", encoding="utf-8")
    env = {"ANTHROPIC_API_KEY": "existante"}

    load_dotenv(env_file, env=env)

    assert env["ANTHROPIC_API_KEY"] == "existante"
