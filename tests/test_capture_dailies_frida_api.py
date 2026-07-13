from capture_dailies import JS_CAPTURE


def test_capture_uses_supported_frida_module_observer_api():
    assert "Process.attachModuleObserver" in JS_CAPTURE
    assert "Process.on('module-load'" not in JS_CAPTURE
