class LanguageManager:
    current_language = "Español"

    @staticmethod
    def set_language(language):
        LanguageManager.current_language = language

    @staticmethod
    def get_language():
        return LanguageManager.current_language

    @staticmethod
    def translate(key):
        """Devuelve la traducción del texto según el idioma actual."""
        translations = {
            "Español": {
                "Guardar cambios": "Guardar cambios",
                "Cerrar": "Cerrar",
                "Seleccionar Tema:": "Seleccionar Tema:",
                "Seleccionar Idioma:": "Seleccionar Idioma:",
                "Cambios guardados": "Cambios guardados",
            },
            "Inglés": {
                "Guardar cambios": "Save changes",
                "Cerrar": "Close",
                "Seleccionar Tema:": "Select Theme:",
                "Seleccionar Idioma:": "Select Language:",
                "Cambios guardados": "Changes saved",
            },
        }
        return translations.get(LanguageManager.current_language, {}).get(key, key)
