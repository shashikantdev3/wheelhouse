import importlib
import os

PLUGIN_DIR = 'plugins'

class PluginManager:
    def __init__(self):
        self.plugins = {}

    def load_plugins(self):
        for fname in os.listdir(PLUGIN_DIR):
            if fname.endswith('.py') and not fname.startswith('_'):
                modname = fname[:-3]
                module = importlib.import_module(f'{PLUGIN_DIR}.{modname}')
                if hasattr(module, 'register'):
                    self.plugins[modname] = module.register()

    def get_plugin(self, name):
        return self.plugins.get(name)

plugin_manager = PluginManager()
plugin_manager.load_plugins() 