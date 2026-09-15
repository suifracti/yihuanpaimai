import unittest
import numpy as np
from scene_roi_router import SceneRoiRouter


class SceneRouterTests(unittest.TestCase):
    def test_only_one_group_per_frame_and_unknown_cold_recovery(self):
        calls=[]
        actual=['settlement']
        def match(group,frame):
            calls.append(group)
            return (1., group == actual[0])
        router=SceneRoiRouter(['world','lobby','auction','settlement'],match)
        for _ in range(5):
            frame=np.zeros((1,1))
            before=len(calls)
            result=router.observe(frame)
            self.assertEqual(len(calls),before+1)
            self.assertEqual(router.observe(frame),result)
            self.assertEqual(len(calls),before+1)
        self.assertEqual(result['scene'],'settlement')
        actual[0]='lobby'
        for _ in range(6):result=router.observe(np.zeros((1,1)))
        self.assertEqual(result['scene'],'lobby')

    def test_wrong_hint_cannot_set_scene_or_starve_recovery(self):
        router=SceneRoiRouter(['world','lobby','auction'],lambda g,f:(1.,g=='auction'))
        router.hint(['lobby'])
        first=router.observe(np.zeros((1,1)))
        self.assertEqual(first['scene'],'UNKNOWN')
        for _ in range(5):last=router.observe(np.zeros((1,1)))
        self.assertEqual(last['scene'],'auction')

    def test_a_miss_suspends_business_and_invalidates_generation(self):
        hit=[True]
        router=SceneRoiRouter(['auction'],lambda g,f:(1.,hit[0]))
        router.observe(np.zeros((1,1)))
        confirmed=router.observe(np.zeros((1,1)))
        hit[0]=False
        missing=router.observe(np.zeros((1,1)))
        self.assertEqual(missing['scene'],'UNKNOWN')
        self.assertEqual(missing['lastConfirmedScene'],'auction')
        self.assertGreater(missing['generation'],confirmed['generation'])

    def test_bounded_fast_retry_and_no_starvation(self):
        actual = ['IN_AUCTION']
        visited = []
        def match(group, frame):
            visited.append(group)
            return (1.0, group == actual[0])
        groups = ['IN_AUCTION', 'SETTLEMENT', 'AUCTION_LOADING', 'OPEN_WORLD', 'WORLD_MAP']
        router = SceneRoiRouter(groups, match, max_fast_retries=2)
        # Confirm IN_AUCTION (takes 2 hits)
        router.observe(np.zeros((1, 1)))
        r = router.observe(np.zeros((1, 1)))
        self.assertEqual(r['scene'], 'IN_AUCTION')
        # Simulate transient miss for 1 frame
        actual[0] = 'TRANSIENT_MISS'
        r1 = router.observe(np.zeros((1, 1)))
        self.assertEqual(r1['scene'], 'UNKNOWN')
        # Next frame is exit check (SETTLEMENT), then IN_AUCTION is retried
        r2 = router.observe(np.zeros((1, 1)))
        self.assertEqual(r2['activeGroup'], 'SETTLEMENT')
        # Return to IN_AUCTION
        actual[0] = 'IN_AUCTION'
        r3 = router.observe(np.zeros((1, 1)))
        self.assertEqual(r3['activeGroup'], 'IN_AUCTION')
        r4 = router.observe(np.zeros((1, 1)))
        self.assertEqual(r4['scene'], 'IN_AUCTION')

        # Now test sustained exit to WORLD_MAP (not a direct exit in following)
        actual[0] = 'WORLD_MAP'
        visited.clear()
        # Observe until WORLD_MAP is confirmed. Fast retries must not starve WORLD_MAP!
        confirmed = False
        for _ in range(15):
            res = router.observe(np.zeros((1, 1)))
            if res['scene'] == 'WORLD_MAP':
                confirmed = True
                break
        self.assertTrue(confirmed, f"WORLD_MAP should be confirmed without starvation, visited: {visited}")

