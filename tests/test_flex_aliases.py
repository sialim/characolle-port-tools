import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gmod'))
from recover_flex_aliases import aliases_from_clips


class FacialSlotTests(unittest.TestCase):
    def clips(self, target='P_bace_toji', source='me_base_toji', time=0):
        return [{'name': 'Face_top', 'keyframes': [{'name': source, 'index': 0}]},
                {'name': 'mayuge', 'keyframes': [{'name': target, 'index': time}]}]

    def test_separate_lash_mesh_follows_matching_face_slot(self):
        clips = self.clips()
        for clip in clips:
            clip['keyframes'].append(dict(clip['keyframes'][0], index=10))
        self.assertEqual(aliases_from_clips(clips, ['PBaceToji', 'MeBaseToji']),
                         {'PBaceToji': 'MeBaseToji'})

    def test_unavailable_expression_does_not_create_broken_rule(self):
        self.assertEqual(aliases_from_clips(self.clips(), ['MeBaseToji']), {})

    def test_different_slot_times_are_not_paired_by_position(self):
        with self.assertRaisesRegex(ValueError, 'times differ'):
            aliases_from_clips(self.clips(time=1), ['PBaceToji', 'MeBaseToji'])

    def test_conflicting_shared_target_is_rejected(self):
        clips = self.clips()
        clips[0]['keyframes'].append({'name': 'me_winL', 'index': 9})
        clips[1]['keyframes'].append({'name': 'P_bace_toji', 'index': 9})
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            aliases_from_clips(clips, ['PBaceToji', 'MeBaseToji', 'MeWinL'])


if __name__ == '__main__':
    unittest.main()
