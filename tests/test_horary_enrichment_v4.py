import unittest

import astro_core as core
import horary_topic_routes_v3 as routes


class HoraryEnrichmentV4Tests(unittest.TestCase):
    def test_new_topic_routes(self):
        self.assertEqual(core.HORARY_TOPIC_SPECS['pet']['quesited_house'], 6)
        self.assertEqual(core.HORARY_TOPIC_SPECS['children']['quesited_house'], 5)
        self.assertEqual(core.HORARY_TOPIC_SPECS['shared_money']['quesited_house'], 8)
        self.assertEqual(core.HORARY_TOPIC_SPECS['hidden']['quesited_house'], 12)

    def test_condition_and_part_of_fortune_enrichment(self):
        planets = {
            'Sun': {'longitude': 150.0, 'sign_index': 5, 'house': 9, 'retrograde': False, 'direction': '순행', 'dignity': 'peregrine', 'dignity_ko': '무권위·페레그린'},
            'Moon': {'longitude': 85.0, 'sign_index': 2, 'house': 6, 'retrograde': False, 'direction': '순행', 'dignity': 'peregrine', 'dignity_ko': '무권위·페레그린'},
            'Mercury': {'longitude': 150.1, 'sign_index': 5, 'house': 9, 'retrograde': False, 'direction': '순행', 'dignity': 'domicile', 'dignity_ko': '본질적 존귀·도머사일'},
            'Venus': {'longitude': 200.0, 'sign_index': 6, 'house': 10, 'retrograde': False, 'direction': '순행', 'dignity': 'domicile', 'dignity_ko': '본질적 존귀·도머사일'},
            'Mars': {'longitude': 100.0, 'sign_index': 3, 'house': 7, 'retrograde': False, 'direction': '순행', 'dignity': 'fall', 'dignity_ko': '추락'},
            'Jupiter': {'longitude': 135.0, 'sign_index': 4, 'house': 8, 'retrograde': False, 'direction': '순행', 'dignity': 'peregrine', 'dignity_ko': '무권위·페레그린'},
            'Saturn': {'longitude': 13.0, 'sign_index': 0, 'house': 4, 'retrograde': True, 'direction': '역행', 'dignity': 'fall', 'dignity_ko': '추락'},
        }
        data = {
            'schema': 'LUNEA_HORARY_V1',
            'angles': {'ASC': {'longitude': 291.0}},
            'cusps': [291.0, 330.0, 11.0, 41.0, 63.0, 84.0, 111.0, 150.0, 191.0, 221.0, 243.0, 264.0],
            'planets': planets,
            'judgment_support': {},
            'meta': {},
        }

        result = routes._enrich_horary_payload(data)
        self.assertEqual(result['meta']['horary_enrichment'], 'LUNEA_HORARY_CONDITION_V4')
        self.assertEqual(result['planets']['Mercury']['solar_condition'], 'cazimi')
        self.assertEqual(result['planets']['Venus']['house_strength'], 'angular')
        self.assertEqual(result['planets']['Saturn']['house_strength'], 'angular')
        self.assertEqual(result['planets']['Mercury']['traditional_dispositor'], 'Mercury')
        self.assertIn('planet_conditions_v4', result['judgment_support'])
        self.assertIn('PartOfFortune', result['points'])
        self.assertIn(result['points']['PartOfFortune']['house'], range(1, 13))


if __name__ == '__main__':
    unittest.main()
