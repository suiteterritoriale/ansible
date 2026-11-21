"""Tests for the `deploy` command (st_cli.cmd.deploy)."""

from __future__ import annotations

import pytest
from helpers import call_order_spy, seed_creds, seed_drive_unit, seed_meet_unit
from typer.testing import CliRunner

import st_cli
from st_cli import main as main_mod
from st_cli.core import (
    drift,
    generate,
    manifest,
    runner,
    sshuser,
    tree,
    ui,
    upgrades,
    upstream,
)
from st_cli.core.errors import StCliError
from st_cli.core.models import StCliManifest, UnitState, UpgradeNeed


def test_deploy_call_order_check_first_then_generate_galaxy_play(repo, mocker):
    """Check that the pending-needs gate runs before generate, galaxy_install, and
    play."""
    seed_meet_unit(repo)
    call_order, spy = call_order_spy()

    mocker.patch.object(
        drift, "pending_needs", spy("pending_needs", drift.pending_needs)
    )
    mocker.patch.object(
        generate, "generate_all", spy("generate_all", lambda *a, **k: None)
    )
    mocker.patch.object(
        runner, "galaxy_install", spy("galaxy_install", lambda *a, **k: None)
    )
    mocker.patch.object(runner, "play", spy("play", lambda *a, **k: 0))

    from st_cli.cmd import deploy as deploy_mod

    deploy_mod.run("meet", "prod", None, dry_run=False, deploy_only=False)

    assert call_order == ["pending_needs", "generate_all", "galaxy_install", "play"]


def test_deploy_resolves_host_alias_to_play_limit(repo, mocker):
    """`deploy -H <alias>` resolves the alias and passes it as
    runner.play(limit=...)."""
    seed_meet_unit(repo)  # writes host meet1 (ansible_host=10.0.0.5)
    mocker.patch.object(generate, "generate_all", lambda *a, **k: None)
    mocker.patch.object(runner, "galaxy_install", lambda *a, **k: None)
    play = mocker.patch.object(runner, "play", return_value=0)

    from st_cli.cmd import deploy as deploy_mod

    deploy_mod.run("meet", "prod", None, dry_run=False, deploy_only=False, host="meet1")
    assert play.call_args.kwargs["limit"] == "meet1"  # the inventory alias

    # no host means limit=None (all hosts)
    deploy_mod.run("meet", "prod", None, dry_run=False, deploy_only=False)
    assert play.call_args.kwargs["limit"] is None


def test_deploy_unknown_host_alias_raises(repo, mocker):
    """`deploy -c <comp> -H <bad-alias>` raises because the host is not in the
    component."""
    import pytest

    from st_cli.core.errors import StCliError

    seed_meet_unit(repo)
    mocker.patch.object(generate, "generate_all", lambda *a, **k: None)
    mocker.patch.object(runner, "galaxy_install", lambda *a, **k: None)
    mocker.patch.object(runner, "play", return_value=0)

    from st_cli.cmd import deploy as deploy_mod

    with pytest.raises(StCliError):
        deploy_mod.run(
            "meet", "prod", ["meet"], dry_run=False, deploy_only=False, host="nope1"
        )


def test_deploy_blocks_when_cli_older_than_pin(repo, mocker, monkeypatch):
    """An installed CLI older than the pin blocks before any ssh/network side effect."""
    seed_meet_unit(repo)  # pin = 0.0.19
    monkeypatch.setattr(st_cli, "__version__", "0.0.10")
    generate_spy = mocker.patch.object(generate, "generate_all")
    galaxy_spy = mocker.patch.object(runner, "galaxy_install")
    ensure_ssh_user = mocker.patch.object(sshuser, "ensure_ssh_user")
    play = mocker.patch.object(runner, "play", return_value=0)

    result = CliRunner().invoke(main_mod.app, ["deploy", "meet", "prod"])
    output = " ".join(result.output.split())  # rich wraps long lines

    assert result.exit_code == 1
    assert "older than the .st-cli.yml pin" in output
    assert upstream.install_hint() in output
    play.assert_not_called()
    ensure_ssh_user.assert_not_called()
    galaxy_spy.assert_not_called()
    generate_spy.assert_not_called()


def test_deploy_aborts_when_rebootstrap_pending(repo, mocker, monkeypatch):
    """A real pending flag at or below the pin blocks deploy before any ssh/network
    call."""
    seed_meet_unit(repo)  # pin = 0.0.19, unit stamp = "" (reads as 0.0.0)
    generate_spy = mocker.patch.object(generate, "generate_all")
    galaxy_install = mocker.patch.object(runner, "galaxy_install")
    ensure_ssh_user = mocker.patch.object(sshuser, "ensure_ssh_user")
    play = mocker.patch.object(runner, "play", return_value=0)
    monkeypatch.setattr(
        upgrades,
        "load_flags",
        lambda: [
            {"version": "0.0.10", "apps": ["meet"], "reason": "reason", "link": ""}
        ],
    )

    result = CliRunner().invoke(main_mod.app, ["deploy", "meet", "prod"])

    assert result.exit_code == 1
    # rich wraps long lines, so check content rather than one exact substring
    assert "Rebootstrap required before deploying" in result.output
    assert "Run `st-cli upgrade` to resume the replay" in result.output
    assert "meet" in result.output and "prod" in result.output
    play.assert_not_called()
    ensure_ssh_user.assert_not_called()
    galaxy_install.assert_not_called()
    generate_spy.assert_not_called()


def test_deploy_runs_normally_when_no_rebootstrap_pending(repo, mocker):
    """Check that deploy proceeds as normal when pending_needs returns no needs."""
    seed_meet_unit(repo)
    mocker.patch.object(generate, "generate_all", lambda *a, **k: None)
    mocker.patch.object(runner, "galaxy_install", lambda *a, **k: None)
    play = mocker.patch.object(runner, "play", return_value=0)

    result = CliRunner().invoke(main_mod.app, ["deploy", "meet", "prod"])

    assert result.exit_code == 0
    play.assert_called_once()


def test_deploy_warns_but_runs_on_pending_flag_above_pin(repo, mocker):
    """A pending flag above the pin warns without blocking deploy."""
    seed_meet_unit(repo)  # pin = 0.0.19
    mocker.patch.object(generate, "generate_all", lambda *a, **k: None)
    mocker.patch.object(runner, "galaxy_install", lambda *a, **k: None)
    need = UpgradeNeed(
        app="meet",
        env="prod",
        component="meet",
        version="0.5.0",
        reason="reason",
        link="",
        full_replay=False,
    )
    mocker.patch.object(drift, "pending_needs", return_value=[need])
    warn_spy = mocker.patch.object(ui, "warn")
    play = mocker.patch.object(runner, "play", return_value=0)

    result = CliRunner().invoke(main_mod.app, ["deploy", "meet", "prod"])

    assert result.exit_code == 0
    play.assert_called_once()
    assert any(
        "meet/prod/meet: rebootstrap needed (0.5.0 — reason). Run `st-cli upgrade`."
        in str(c.args[0])
        for c in warn_spy.call_args_list
    )


def test_deploy_next_flag_warns_and_runs(repo, mocker, monkeypatch):
    """A `next` flag warns and lets deploy run."""
    seed_meet_unit(repo)  # pin = 0.0.19, unit stamp = "" (reads as 0.0.0)
    mocker.patch.object(generate, "generate_all", lambda *a, **k: None)
    mocker.patch.object(runner, "galaxy_install", lambda *a, **k: None)
    warn_spy = mocker.patch.object(ui, "warn")
    play = mocker.patch.object(runner, "play", return_value=0)
    monkeypatch.setattr(
        upgrades,
        "load_flags",
        lambda: [{"version": "next", "apps": ["meet"], "reason": "reason"}],
    )

    result = CliRunner().invoke(main_mod.app, ["deploy", "meet", "prod"])

    assert result.exit_code == 0
    play.assert_called_once()
    assert any(
        "meet/prod/meet: rebootstrap needed (next — reason). Run `st-cli upgrade`."
        in str(c.args[0])
        for c in warn_spy.call_args_list
    )


def test_deploy_warn_line_omits_warning_text(repo, mocker):
    """A pending need's warnings stay out of the deploy warn line."""
    seed_meet_unit(repo)  # pin = 0.0.19
    mocker.patch.object(generate, "generate_all", lambda *a, **k: None)
    mocker.patch.object(runner, "galaxy_install", lambda *a, **k: None)
    need = UpgradeNeed(
        app="meet",
        env="prod",
        component="meet",
        version="0.5.0",
        reason="reason",
        link="",
        full_replay=False,
        warnings=("S3_REPLICATION_BUCKET must now start with https://",),
    )
    mocker.patch.object(drift, "pending_needs", return_value=[need])
    warn_spy = mocker.patch.object(ui, "warn")
    play = mocker.patch.object(runner, "play", return_value=0)

    result = CliRunner().invoke(main_mod.app, ["deploy", "meet", "prod"])

    assert result.exit_code == 0
    play.assert_called_once()
    assert not any(
        "S3_REPLICATION_BUCKET" in str(c.args[0]) for c in warn_spy.call_args_list
    )


def test_deploy_blocking_message_omits_warning_text(repo, mocker):
    """A blocking need's warnings stay out of the deploy-blocking message."""
    seed_meet_unit(repo)  # pin = 0.0.19
    mocker.patch.object(generate, "generate_all", lambda *a, **k: None)
    galaxy_install = mocker.patch.object(runner, "galaxy_install")
    need = UpgradeNeed(
        app="meet",
        env="prod",
        component="meet",
        version="0.0.5",
        reason="reason",
        link="",
        full_replay=False,
        warnings=("rotate the OIDC secret by hand",),
    )
    mocker.patch.object(drift, "pending_needs", return_value=[need])
    play = mocker.patch.object(runner, "play", return_value=0)

    result = CliRunner().invoke(main_mod.app, ["deploy", "meet", "prod"])
    output = " ".join(result.output.split())  # rich wraps long lines

    assert result.exit_code == 1
    assert "rotate the OIDC secret by hand" not in output
    assert "Run `st-cli upgrade` to resume the replay." in output
    play.assert_not_called()
    galaxy_install.assert_not_called()


def test_deploy_blocking_message_includes_link(repo, mocker):
    """A blocking need's link does not appear in the deploy-blocking message."""
    seed_meet_unit(repo)  # pin = 0.0.19
    mocker.patch.object(generate, "generate_all", lambda *a, **k: None)
    galaxy_install = mocker.patch.object(runner, "galaxy_install")
    need = UpgradeNeed(
        app="meet",
        env="prod",
        component="meet",
        version="0.0.5",
        reason="reason",
        link="https://example.org/changelog#v005",
        full_replay=False,
    )
    mocker.patch.object(drift, "pending_needs", return_value=[need])
    play = mocker.patch.object(runner, "play", return_value=0)

    result = CliRunner().invoke(main_mod.app, ["deploy", "meet", "prod"])
    output = " ".join(result.output.split())  # rich wraps long lines

    assert result.exit_code == 1
    assert "https://example.org/changelog#v005" not in output
    play.assert_not_called()
    galaxy_install.assert_not_called()


def test_deploy_warns_with_format_need_text_on_real_flag_data(
    repo, mocker, monkeypatch
):
    """A real flag above the pin warns with `drift.format_need`'s exact text, and
    the deploy still runs."""
    seed_meet_unit(repo)  # pin = 0.0.19, unit stamp reads as 0.0.0
    monkeypatch.setattr(
        upgrades,
        "load_flags",
        lambda: [
            {
                "version": "0.5.0",
                "apps": ["meet"],
                "reason": "reason",
                "link": "",
                "warnings": ["rotate the OIDC secret by hand"],
            }
        ],
    )
    mocker.patch.object(generate, "generate_all", lambda *a, **k: None)
    mocker.patch.object(runner, "galaxy_install", lambda *a, **k: None)
    warn_spy = mocker.patch.object(ui, "warn")
    play = mocker.patch.object(runner, "play", return_value=0)

    result = CliRunner().invoke(main_mod.app, ["deploy", "meet", "prod"])

    assert result.exit_code == 0
    play.assert_called_once()
    need = UpgradeNeed(
        app="meet",
        env="prod",
        component="meet",
        version="0.5.0",
        reason="reason",
        link="",
        full_replay=False,
        warnings=("rotate the OIDC secret by hand",),
    )
    warn_spy.assert_any_call(drift.format_need("meet", "prod", need))
    assert not any(
        "rotate the OIDC secret by hand" in str(c.args[0])
        for c in warn_spy.call_args_list
    )


def test_deploy_baseline_synthetic_flag_warns_and_runs(repo, mocker, monkeypatch):
    """A unit stamped below the baseline warns through the synthetic flag when
    the installed CLI is newer than the pin, and the deploy still runs."""
    seed_creds(repo)
    manifest.save_manifest(
        StCliManifest(
            "0.1.0",
            "0.1.0",
            [UnitState("meet", "prod", "meet", "managed", "0.1.0")],
        )
    )
    data = tree.load_vars("meet", "prod", "meet")
    data["st_meet_backend_env"] = "DJANGO_CONFIGURATION=Production\n"
    tree.save_vars("meet", "prod", "meet", data)
    tree.write_hosts("meet", "prod", "meet", "meet", ["10.0.0.5"])

    monkeypatch.setattr(st_cli, "__version__", "0.3.0")
    monkeypatch.setattr(upgrades, "load_baseline", lambda: "0.2.0")
    monkeypatch.setattr(upgrades, "load_flags", list)
    mocker.patch.object(generate, "generate_all", lambda *a, **k: None)
    mocker.patch.object(runner, "galaxy_install", lambda *a, **k: None)
    warn_spy = mocker.patch.object(ui, "warn")
    play = mocker.patch.object(runner, "play", return_value=0)

    result = CliRunner().invoke(main_mod.app, ["deploy", "meet", "prod"])

    assert result.exit_code == 0
    play.assert_called_once()
    assert any("no longer supported" in str(c.args[0]) for c in warn_spy.call_args_list)


def test_deploy_baseline_synthetic_flag_blocks_after_crashed_upgrade(
    repo, mocker, monkeypatch
):
    """A unit stamped below the baseline blocks deploy once the pin matches the
    installed CLI, because an earlier upgrade crashed before the replay finished."""
    seed_creds(repo)
    manifest.save_manifest(
        StCliManifest(
            "0.2.0",
            "0.2.0",
            [UnitState("meet", "prod", "meet", "managed", "0.1.0")],
        )
    )
    data = tree.load_vars("meet", "prod", "meet")
    data["st_meet_backend_env"] = "DJANGO_CONFIGURATION=Production\n"
    tree.save_vars("meet", "prod", "meet", data)
    tree.write_hosts("meet", "prod", "meet", "meet", ["10.0.0.5"])

    monkeypatch.setattr(st_cli, "__version__", "0.2.0")
    monkeypatch.setattr(upgrades, "load_baseline", lambda: "0.2.0")
    monkeypatch.setattr(upgrades, "load_flags", list)
    generate_spy = mocker.patch.object(generate, "generate_all")
    galaxy_install = mocker.patch.object(runner, "galaxy_install")
    play = mocker.patch.object(runner, "play", return_value=0)

    result = CliRunner().invoke(main_mod.app, ["deploy", "meet", "prod"])

    assert result.exit_code == 1
    assert "resume the replay" in result.output
    play.assert_not_called()
    galaxy_install.assert_not_called()
    generate_spy.assert_not_called()


def test_deploy_two_components_runs_play_for_each(repo, mocker):
    """`st-cli deploy APP ENV -c drive -c collabora` runs runner.play once per
    requested component, in deploy_order."""
    seed_drive_unit(
        repo,
        components=("drive", "collabora"),
        component_hosts={"drive": ["10.0.0.1"], "collabora": ["10.0.0.3"]},
    )
    mocker.patch.object(generate, "generate_all", lambda *a, **k: None)
    mocker.patch.object(runner, "galaxy_install", lambda *a, **k: None)
    play = mocker.patch.object(runner, "play", return_value=0)

    result = CliRunner().invoke(
        main_mod.app, ["deploy", "drive", "prod", "-c", "collabora", "-c", "drive"]
    )

    assert result.exit_code == 0
    assert play.call_count == 2
    played = [c.args[2] for c in play.call_args_list]  # play(app, env, component, ...)
    assert played == ["collabora", "drive"]  # deploy_order sort applied


def test_deploy_env_key_advisory_does_not_block(repo, mocker):
    """Check that an env-key advisory alone does not block the deploy."""
    seed_meet_unit(repo)
    mocker.patch.object(generate, "generate_all", lambda *a, **k: None)
    mocker.patch.object(runner, "galaxy_install", lambda *a, **k: None)
    mocker.patch.object(
        drift,
        "env_key_report",
        lambda *a, **k: [
            "meet/prod/meet: new env keys available: FOO — run `st-cli bootstrap meet prod` to set them."
        ],
    )
    warn_spy = mocker.patch.object(ui, "warn")
    play = mocker.patch.object(runner, "play", return_value=0)

    result = CliRunner().invoke(main_mod.app, ["deploy", "meet", "prod"])

    assert result.exit_code == 0
    play.assert_called_once()
    warn_spy.assert_any_call(
        "meet/prod/meet: new env keys available: FOO — run "
        "`st-cli bootstrap meet prod` to set them."
    )


def test_deploy_rebootstrap_flag_still_blocks_even_with_clean_env_keys(
    repo, mocker, monkeypatch
):
    """Check that a blocking flag still blocks the deploy regardless of
    env_key_report."""
    seed_meet_unit(repo)  # pin = 0.0.19
    mocker.patch.object(generate, "generate_all", lambda *a, **k: None)
    mocker.patch.object(runner, "galaxy_install", lambda *a, **k: None)
    monkeypatch.setattr(
        upgrades,
        "load_flags",
        lambda: [
            {"version": "0.0.5", "apps": ["meet"], "reason": "reason", "link": ""}
        ],
    )
    env_key_report_spy = mocker.patch.object(drift, "env_key_report", return_value=[])
    play = mocker.patch.object(runner, "play", return_value=0)

    result = CliRunner().invoke(main_mod.app, ["deploy", "meet", "prod"])

    assert result.exit_code == 1
    play.assert_not_called()
    env_key_report_spy.assert_not_called()  # the gate raises before it is reached


# ------------------------------------------------- required dependency gate (docs/yhub)


def _docs_skipping_yhub(repo, monkeypatch):
    from helpers import docs_first_run_script, script_questionary

    from st_cli.cmd import bootstrap

    seed_creds(repo)
    script_questionary(monkeypatch, docs_first_run_script())
    bootstrap.bootstrap("docs", "prod")


def _no_side_effects(mocker):
    gen = mocker.patch.object(generate, "generate_all")
    galaxy = mocker.patch.object(runner, "galaxy_install")
    play = mocker.patch.object(runner, "play", return_value=0)
    ssh = mocker.patch.object(sshuser, "ensure_ssh_user")
    return gen, galaxy, play, ssh


def _deploy(components=None):
    from st_cli.cmd import deploy as deploy_mod

    deploy_mod.run("docs", "prod", components, dry_run=False, deploy_only=False)


@pytest.mark.parametrize("components", [None, ["docs"], ["workers"]])
def test_deploy_refuses_docs_when_the_user_skipped_yhub(
    repo, monkeypatch, mocker, components
):
    """Docs 6 opens no document without yhub: deploy refuses before any ssh,
    generate or play."""
    _docs_skipping_yhub(repo, monkeypatch)
    calls = _no_side_effects(mocker)

    with pytest.raises(StCliError) as exc:
        _deploy(components)

    msg = str(exc.value)
    assert "yhub is required and has no unit" in msg
    assert "Run `st-cli bootstrap docs prod` and answer" in msg
    assert '"Yes — bootstrap now" (or "Already deployed (enter URL + keys)")' in msg
    assert "-c yhub" not in msg
    assert "st-cli upgrade" not in msg
    for call in calls:
        call.assert_not_called()


def test_deploy_gate_passes_after_the_yhub_bootstrap_and_a_core_replay(
    repo, monkeypatch, mocker
):
    from helpers import ACCEPT_DEFAULT, accept_defaults, docs_yhub_script

    from st_cli.cmd import bootstrap

    _docs_skipping_yhub(repo, monkeypatch)
    script = docs_yhub_script()
    script.append(("text", "Public domain for docs (for", ACCEPT_DEFAULT))
    accept_defaults(monkeypatch, script)
    bootstrap.bootstrap("docs", "prod", component="yhub")
    _, _, play, _ = _no_side_effects(mocker)

    # the yhub unit exists, but the core blobs do not name it yet
    with pytest.raises(StCliError) as exc:
        _deploy()
    assert "does not name yhub yet" in str(exc.value)
    assert "`st-cli bootstrap docs prod`" in str(exc.value)
    play.assert_not_called()

    # a run that targets only yhub rolls out nothing that needs it
    _deploy(["yhub"])
    assert play.call_count == 1

    accept_defaults(
        monkeypatch,
        [
            ("select", "Database configuration:", "DATABASE_URL"),
            ("select", "Bootstrap yhub now?", "Reuse existing in the repo"),
        ],
    )
    bootstrap.bootstrap("docs", "prod", replay=bootstrap.ReplayAction.MODIFY)
    _deploy()
    assert play.call_count > 1


def test_deploy_gate_passes_with_an_external_yhub(repo, monkeypatch, mocker):
    from helpers import docs_first_run_script, script_questionary

    from st_cli.cmd import bootstrap

    seed_creds(repo)
    script_questionary(
        monkeypatch,
        docs_first_run_script(yhub="Already deployed (enter URL + keys)")
        + [
            ("text", "yhub endpoints", "10.0.0.9:50601"),
            ("text", "YHUB_API_BASE_URL", "http://yhub.internal:50601"),
            ("password", "Y_PROVIDER_API_KEY", "ext-key"),
        ],
    )
    bootstrap.bootstrap("docs", "prod")
    _, _, play, _ = _no_side_effects(mocker)

    _deploy()

    assert play.call_count >= 1


@pytest.mark.parametrize("components", [None, ["docs"], ["yprovider"]])
def test_deploy_refuses_a_v5_tree_that_is_not_upgraded(
    repo, monkeypatch, mocker, components
):
    """The new role is v6: a v5 tree must go through `st-cli upgrade` first,
    and the legacy cleanup play must not remove yprovider before."""
    from helpers import seed_docs_v5_tree

    seed_docs_v5_tree(repo)
    m = manifest.load_manifest()
    for u in m.units:
        u.bootstrapped_with = st_cli.__version__
    manifest.save_manifest(m)
    mocker.patch.object(drift, "pending_needs", return_value=[])
    calls = _no_side_effects(mocker)

    with pytest.raises(StCliError) as exc:
        _deploy(components)

    assert "this tree is not upgraded" in str(exc.value)
    assert "Run `st-cli upgrade` and answer" in str(exc.value)
    for call in calls:
        call.assert_not_called()


def test_dependency_gaps_leave_the_other_apps_alone(repo):
    """Only a dependency marked `required` blocks: meet keeps livekit optional."""
    seed_meet_unit(repo)
    assert drift.dependency_gaps("meet", "prod") == []
    drift.require_dependencies("meet", "prod")


def test_doctor_sweep_reports_the_missing_required_dependency(repo, monkeypatch):
    _docs_skipping_yhub(repo, monkeypatch)
    warnings = drift.preflight_all("docs", "prod")
    assert any("yhub is required and has no unit" in w for w in warnings)


def test_reset_is_covered_by_the_same_gate(repo, monkeypatch, mocker):
    """`reset` tears the unit down before the redeploy: the gate comes first."""
    from st_cli.cmd import remote

    _docs_skipping_yhub(repo, monkeypatch)
    ssh = mocker.patch.object(remote, "_ssh", return_value=0)

    with pytest.raises(StCliError, match="yhub is required"):
        remote.reset("docs", "prod", "docs", assume_yes=True)

    ssh.assert_not_called()


def _follow_bootstrap_docs(monkeypatch, label):
    """Run the command that the gate message names: `st-cli bootstrap docs prod`,
    answering `label` for yhub."""
    from helpers import accept_defaults, docs_yhub_script

    from st_cli.cmd import bootstrap

    yhub = (
        docs_yhub_script()
        if label.startswith("Yes")
        else [
            ("text", "yhub endpoints", "10.0.0.9:50601"),
            ("text", "YHUB_API_BASE_URL", "http://yhub.internal:50601"),
            ("password", "Y_PROVIDER_API_KEY", "ext-key"),
        ]
    )
    accept_defaults(
        monkeypatch,
        [
            ("select", "Database configuration:", "DATABASE_URL"),
            ("select", "Bootstrap yhub now?", label),
            *yhub,
        ],
    )
    bootstrap.bootstrap("docs", "prod", replay=bootstrap.ReplayAction.MODIFY)


@pytest.mark.parametrize(
    "label", ["Yes — bootstrap now", "Already deployed (enter URL + keys)"]
)
def test_the_no_unit_message_names_a_command_that_clears_the_gate(
    repo, monkeypatch, label
):
    _docs_skipping_yhub(repo, monkeypatch)
    with pytest.raises(StCliError, match="has no unit"):
        drift.require_dependencies("docs", "prod")

    _follow_bootstrap_docs(monkeypatch, label)

    drift.require_dependencies("docs", "prod")


def test_the_later_warning_names_a_command_that_clears_the_gate(
    repo, monkeypatch, capfd
):
    """A v5 tree upgraded with "later": the warning, followed literally, clears
    the gate."""
    from helpers import accept_defaults, seed_docs_v5_tree

    from st_cli.cmd import upgrade as upgrade_mod

    seed_docs_v5_tree(repo)
    accept_defaults(
        monkeypatch,
        [
            ("select", "Database configuration:", "DATABASE_URL"),
            ("select", "Bootstrap yhub now?", "No — bootstrap later"),
        ],
    )
    upgrade_mod.upgrade()
    err = " ".join(capfd.readouterr().err.split())
    assert (
        'run `st-cli bootstrap docs prod` and answer "Yes — bootstrap now" for yhub'
        in err
    )
    with pytest.raises(StCliError):
        drift.require_dependencies("docs", "prod")

    _follow_bootstrap_docs(monkeypatch, "Yes — bootstrap now")

    drift.require_dependencies("docs", "prod")


def test_the_not_upgraded_message_names_a_command_that_clears_the_gate(
    repo, monkeypatch
):
    """`st-cli upgrade`, answering yes for yhub in that run, clears the gate."""
    from helpers import accept_defaults, docs_yhub_script, seed_docs_v5_tree

    from st_cli.cmd import upgrade as upgrade_mod

    seed_docs_v5_tree(repo)
    with pytest.raises(StCliError, match="not upgraded"):
        drift.require_dependencies("docs", "prod")
    accept_defaults(
        monkeypatch,
        [
            ("select", "Database configuration:", "DATABASE_URL"),
            ("select", "Bootstrap yhub now?", "Yes — bootstrap now"),
            *docs_yhub_script(),
        ],
    )

    upgrade_mod.upgrade()

    drift.require_dependencies("docs", "prod")


@pytest.mark.parametrize("empty", ["", "   ", '""', "''"])
def test_gate_treats_an_empty_looking_value_as_not_wired(repo, monkeypatch, empty):
    from helpers import seed_docs_yhub_unit

    seed_docs_yhub_unit(repo)
    meta_core_vars = tree.load_vars("docs", "prod", "docs")
    meta_core_vars["st_docs_caddy_env"] = f"CADDY_YHUB_ENDPOINTS={empty}\n"
    meta_core_vars["st_docs_backend_env"] = "YHUB_API_BASE_URL=http://y:50601\n"
    tree.save_vars("docs", "prod", "docs", meta_core_vars)
    m = manifest.load_manifest()
    manifest.upsert_unit(m, UnitState("docs", "prod", "docs", "managed"))
    manifest.save_manifest(m)

    with pytest.raises(StCliError, match="does not name yhub yet"):
        drift.require_dependencies("docs", "prod")


def test_dependency_gaps_do_not_read_the_core_of_an_app_without_one(repo, mocker):
    seed_meet_unit(repo)
    spy = mocker.patch.object(drift.recover, "recover")
    assert drift.dependency_gaps("meet", "prod") == []
    spy.assert_not_called()
