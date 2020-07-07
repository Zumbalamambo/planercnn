"""
Copyright Jan Wietrzykowski 2020
"""

import numpy as np
import cv2
import sys
import os
import torch
import torchvision

from options import parse_args
from config import PlaneConfig
import utils

ROOT_FOLDER = "/mnt/data/datasets/JW/scenenet_rgbd/scenes/"


def calc_iou(box1, box2):
    y1_i = max(box1[0], box2[0])
    y2_i = min(box1[2], box2[2])
    x1_i = max(box1[1], box2[1])
    x2_i = min(box1[3], box2[3])

    area_i = (y2_i - y1_i) * (x2_i - x1_i)
    area_1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area_2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    iou = area_i / (area_1 + area_2 - area_i)

    return iou


def remove_nms(anchors, scores):
    iou_thresh = 0.7

    sort_idxs = np.argsort(scores)

    keep_idxs = np.full(anchors.shape[0], fill_value=True)
    for i in range(anchors.shape[0]):
        for j in range(i + 1, anchors.shape[0]):
            iou = calc_iou(anchors[sort_idxs[i]], anchors[sort_idxs[j]])
            if iou > iou_thresh:
                keep_idxs[sort_idxs[j]] = False

    nms_anchors = anchors[keep_idxs]
    nms_scores = scores[keep_idxs]

    return nms_anchors, nms_scores, keep_idxs


def test_planes(scene_id, config):
    images_list = sorted(os.listdir(os.path.join(ROOT_FOLDER, scene_id, 'frames', 'color_left')))

    anchors = utils.generate_pyramid_anchors(config.RPN_ANCHOR_SCALES,
                                             config.RPN_ANCHOR_RATIOS,
                                             config.BACKBONE_SHAPES,
                                             config.BACKBONE_STRIDES,
                                             config.RPN_ANCHOR_STRIDE)
    anchors = torch.from_numpy(anchors).float()

    K = np.array([[554.256, 0.0, 320.0],
                  [0.0, 579.411, 240.0],
                  [0.0, 0.0, 1.0]], dtype=np.float)
    for im_file in images_list:
        im = cv2.imread(os.path.join(ROOT_FOLDER, scene_id, 'frames', 'color_left', im_file))
        depth = cv2.imread(os.path.join(ROOT_FOLDER, scene_id, 'frames', 'depth_left', im_file.replace('.jpg', '.png')),
                           cv2.IMREAD_ANYDEPTH) / 1000.0

        points = utils.calc_points_depth(depth, K)
        points = np.expand_dims(np.transpose(points, axes=(2, 0, 1)), axis=0)
        points = torch.from_numpy(points).float()
        scores = []
        anchor_points = torchvision.ops.roi_align(points,
                                                  [anchors],
                                                  (config.MASK_SHAPE[0], config.MASK_SHAPE[1]))

        for idx, cur_points in enumerate(anchor_points):
            if idx % 1000 == 0:
                print('idx = ', idx)

            cur_points = cur_points.reshape((3, -1)).transpose(0, 1)
            valid_points = cur_points[torch.norm(cur_points, dim=-1) > 1e-3]
            if valid_points.shape[0] > 0:
                mask = utils.fit_plane_ransac(valid_points.reshape(-1, 3))
                num_inliers = torch.sum(mask)
            else:
                num_inliers = torch.zeros(1)
            # print('num_inliners = ', num_inliers, ', num points = ', cur_points.shape[0])
            cur_score = num_inliers.float() / cur_points.shape[0]
            # print('cur_score = ', cur_score)
            scores.append(cur_score)

        # for cur_anch in anchors:
        #     y1, x1, y2, x2 = cur_anch

            # cur_depth = utils.roi_align_vectorized(depth, cur_anch, int(y2 - y1), int(x2 - x1))
            # cur_points = utils.apply_anchor(points, cur_anch)
            # cur_points_x = utils.roi_align_vectorized(points[:, :, 0], cur_anch, int(y2 - y1), int(x2 - x1))
            # cur_points_y = utils.roi_align_vectorized(points[:, :, 1], cur_anch, int(y2 - y1), int(x2 - x1))
            # cur_points_z = utils.roi_align_vectorized(points[:, :, 2], cur_anch, int(y2 - y1), int(x2 - x1))
            # cur_points = np.stack([cur_points_x, cur_points_y, cur_points_z], axis=-1)
            # valid_points = cur_points[np.linalg.norm(cur_points, axis=-1) > 1e-3]

            # num_inliers = utils.fit_plane_ransac(valid_points.reshape(-1, 3))
            # cur_score = num_inliers / (cur_points.shape[0] * cur_points.shape[1])
            # scores.append(cur_score)

        # nms_anchors, nms_scores, keep_idxs = remove_nms(anchors, scores)
        scores = torch.tensor(scores)
        keep = torchvision.ops.nms(anchors, scores, 0.3)

        for idx in range(keep.shape[0]):
            pt1 = anchors[keep[idx], 0:2].numpy()
            pt2 = anchors[keep[idx], 2:4].numpy()
            cv2.rectangle(im, (pt1[0], pt1[1]), (pt2[0], pt2[1]), (0, 0, 255), 2)
            if idx > 0:
                iou = calc_iou(anchors[keep[idx - 1]], anchors[keep[idx]])
                print('keep[idx - 1] = ', keep[idx - 1], ', keep[idx] = ', keep[idx])
                print('iou = ', iou, ', score1 = ', scores[keep[idx - 1]], ', score2 = ', scores[keep[idx]])
            cv2.imshow('planes', im)
            cv2.waitKey()


def main():
    args = parse_args()

    args.keyname = 'planercnn'

    args.keyname += '_' + args.anchorType
    if args.dataset != '':
        args.keyname += '_' + args.dataset
        pass
    if args.trainingMode != 'all':
        args.keyname += '_' + args.trainingMode
        pass
    if args.suffix != '':
        args.keyname += '_' + args.suffix
        pass

    args.checkpoint_dir = 'checkpoint/' + args.keyname
    args.test_dir = 'test/' + args.keyname

    scene_ids = os.listdir(ROOT_FOLDER)
    scene_ids = sorted(scene_ids)
    print(scene_ids)

    np.random.seed(13)

    config = PlaneConfig(args)

    for index, scene_id in enumerate(scene_ids):
        print(index, scene_id)
        test_planes(scene_id, config)


if __name__=='__main__':
    main()
