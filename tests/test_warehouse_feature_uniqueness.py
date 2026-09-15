import unittest
from unittest.mock import Mock

import cv2
import numpy as np

from warehouse_placement_resolver import WarehousePlacementResolver


class FeatureUniquenessTests(unittest.TestCase):
    def points(self, coords):
        return [cv2.KeyPoint(float(x), float(y), 3) for x, y in coords]

    def match(self, source, target, distance=1):
        return cv2.DMatch(source, target, float(distance))

    def test_orientation_duplicates_count_as_one_location(self):
        points = self.points([(5, 5), (5, 5), (20, 5), (20, 5)])
        matches = [self.match(i, i) for i in range(4)]
        selected = WarehousePlacementResolver._distinct_feature_matches(matches, points, points)
        self.assertEqual([(m.queryIdx, m.trainIdx) for m in selected], [(0, 0), (2, 2)])

    def test_both_ends_must_be_unique_and_best_distance_wins(self):
        source = self.points([(0, 0), (0, 0), (20, 0), (40, 0)])
        target = self.points([(0, 0), (20, 0), (20, 0), (40, 0)])
        matches = [self.match(0, 0, 4), self.match(1, 1, 1), self.match(2, 2, 2), self.match(3, 3, 1)]
        selected = WarehousePlacementResolver._distinct_feature_matches(matches, source, target)
        self.assertEqual([(m.queryIdx, m.trainIdx) for m in selected], [(1, 1), (3, 3)])

    def resolver(self, coords):
        resolver = WarehousePlacementResolver.__new__(WarehousePlacementResolver)
        points = self.points(coords)
        descriptor = np.zeros((len(points), 128), np.float32)
        pairs = [[self.match(i, i), self.match(i, (i + 1) % len(points), 10)] for i in range(len(points))]
        resolver._matcher = Mock()
        resolver._matcher.knnMatch.return_value = pairs
        reference = {'kp': points, 'des': descriptor}
        return resolver, reference, (points, descriptor)

    def test_real_model_fit_cannot_turn_four_locations_into_eight_inliers(self):
        resolver, reference, query = self.resolver([(5, 5), (5, 5), (25, 5), (25, 5), (5, 25), (5, 25), (25, 25), (25, 25)])
        count = resolver._compute_sift_inliers(np.zeros((40, 40, 3), np.uint8), reference, query)
        self.assertEqual(count, 4)

    def test_seven_distinct_consistent_locations_remain_seven(self):
        resolver, reference, query = self.resolver([(5, 5), (25, 5), (5, 25), (25, 25), (15, 10), (10, 20), (30, 15)])
        count = resolver._compute_sift_inliers(np.zeros((40, 40, 3), np.uint8), reference, query)
        self.assertEqual(count, 7)

    def test_incomplete_nearest_neighbor_pairs_are_rejected_without_crashing(self):
        resolver, reference, query = self.resolver([(5, 5), (25, 5), (5, 25), (25, 25)])
        resolver._matcher.knnMatch.return_value = [[], [self.match(0, 0)], [], []]
        self.assertEqual(resolver._compute_sift_inliers(np.zeros((40, 40, 3), np.uint8), reference, query), 0)
