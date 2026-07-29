import unittest

from core.utils.context_prefetch import is_weather_context_configured


class WeatherContextConfigurationTests(unittest.TestCase):
    def test_requires_explicit_weather_plugin_credentials(self):
        self.assertFalse(is_weather_context_configured({}))
        self.assertFalse(
            is_weather_context_configured(
                {"plugins": {"search_from_ragflow": {"api_key": "rag-key"}}}
            )
        )
        self.assertFalse(
            is_weather_context_configured(
                {"plugins": {"get_weather": {"api_host": "weather.example.com"}}}
            )
        )
        self.assertFalse(
            is_weather_context_configured(
                {
                    "plugins": {
                        "get_weather": {
                            "api_host": "weather.example.com",
                            "api_key": "你的天气API密钥",
                        }
                    }
                }
            )
        )

    def test_accepts_explicit_weather_plugin_credentials(self):
        self.assertTrue(
            is_weather_context_configured(
                {
                    "plugins": {
                        "get_weather": {
                            "api_host": "weather.example.com",
                            "api_key": "configured-key",
                        }
                    }
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
