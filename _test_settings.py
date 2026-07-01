import sys
import tempfile
import os
from pathlib import Path
from PyQt6.QtWidgets import QApplication

# Isolate config to a temp dir BEFORE importing ConfigManager
tmp_dir = Path(tempfile.mkdtemp())
os.environ["HOME"] = str(tmp_dir)

from core.config import ConfigManager
from core.models import Provider, ModelPricing
from gui.widgets.settings_panel import SettingsPanel


app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

cfg = ConfigManager()

# --- 1. Default providers ---
providers = cfg.load_providers()
print(f"1. Default providers: {len(providers)}")
assert len(providers) >= 2
assert any(p.id == "ollama" for p in providers)
print(f"   Found: {[p.name for p in providers]}")
print("   OK")

# --- 2. Add a custom provider ---
new_prov = Provider(
    id="deepseek_test",
    name="DeepSeek Test",
    base_url="https://api.deepseek.com/v1",
    api_key="sk-test-key",
    models={"deepseek-chat": ModelPricing(input_cost_per_1k=0.0001, output_cost_per_1k=0.0002)},
    default_model="deepseek-chat",
)
providers = cfg.add_provider(new_prov)
assert len(providers) == 3
print(f"2. After add: {len(providers)} providers")
print("   OK")

# --- 3. Remove a provider ---
providers = cfg.remove_provider("deepseek_test")
assert len(providers) == 2
print(f"3. After remove: {len(providers)} providers")
print("   OK")

# --- 4. App config round-trip ---
saved = cfg.load_app_config()
saved["temperature"] = 0.7
saved["style"] = "адаптированный"
cfg.save_app_config(saved)
loaded = cfg.load_app_config()
assert loaded["temperature"] == 0.7
assert loaded["style"] == "адаптированный"
print(f"4. App config: temp={loaded['temperature']}, style={loaded['style']}")
print("   OK")

# --- 5. Settings panel widget ---
panel = SettingsPanel(config_manager=cfg)
panel.show()

signal_data = {"called": 0}
def on_changed():
    signal_data["called"] += 1
panel.settings_changed.connect(on_changed)

# Initial state
assert not panel.is_comparison_enabled()
assert panel.get_temperature() == 0.7  # from step 4
assert panel.get_style() == "адаптированный"
print(f"5. Initial state: temp={panel.get_temperature()}, style='{panel.get_style()}'")
print("   OK")

# Change values
panel._temp_spin.setValue(0.5)
panel._style_combo.setCurrentText("дословный")
assert panel.get_temperature() == 0.5
assert panel.get_style() == "дословный"
print(f"6. After change: temp={panel.get_temperature()}, style='{panel.get_style()}'")
print("   OK")

# Comparison toggle
panel._compare_check.setChecked(True)
assert panel.is_comparison_enabled()
assert panel._model_b_combo.isVisible()
print("7. Comparison enabled, Model B visible: OK")

# Model A/B
panel._model_a_combo.setCurrentText("gpt-4o")
panel._model_b_combo.setCurrentText("deepseek-chat")
panel.save_settings()
saved_cfg = cfg.load_app_config()
assert saved_cfg["last_model_a"] == "gpt-4o"
assert saved_cfg["last_model_b"] == "deepseek-chat"
print(f"8. Models: A={panel.get_model_a()}, B={panel.get_model_b()}")
print("   OK")

# Provider list
assert panel._provider_list.count() >= 2
print(f"9. Provider list items: {panel._provider_list.count()}")
print("   OK")

panel.close()
print()
print("ALL TESTS PASSED")
sys.stdout.flush()
