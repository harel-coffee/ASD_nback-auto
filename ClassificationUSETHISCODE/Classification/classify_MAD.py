
import numpy as np
from scipy.io import loadmat, savemat
from sklearn.linear_model import RidgeClassifierCV
import sklearn
from sklearn.model_selection import RepeatedStratifiedKFold
import scipy
import sklearn.pipeline
import pickle
import argparse
import os
from tqdm import tqdm
from classify import get_classifier

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--alt', action='store_true')
    parser.add_argument('--distractor-diff', action='store_true')
    parser.add_argument('--short-irf', action='store_true')
    parser.add_argument('--dtype', type=str, default='hit')
    parser.add_argument('--n-jobs', type=int, default=1)
    parser.add_argument('--plot', action='store_true')
    parser.add_argument('--outer-cv', type=int, default=1)
    parser.add_argument('--measure', type=str, choices=['MAD', 'MaxAD', 'MeanAD', 'MADs'], default='MAD')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--compute-nulldist', action='store_true')
    args = parser.parse_args()

    # load the data from matlab (see classify.m for how it was saved)
    irf_tag = '_2s' if args.short_irf else ''
    alt_tag = '_a' if args.alt else '_distractors-diff' if args.distractor_diff else ''
    data = loadmat(f'data/XY{irf_tag}{alt_tag}_{args.dtype}.mat')
    X = data['data']['X'][0][0]
    Y = data['data']['Y'][0][0].flatten()

    # compute MAD
    if args.distractor_diff:
        # we calculated MAD ahead of time, just make 2D
        if args.measure != 'MAD':
            raise ValueError()
    else:
        if args.measure == 'MAD':
            X = np.expand_dims(scipy.stats.median_absolute_deviation(X, axis=1),1)
        elif args.measure == 'MaxAD':
            X = np.expand_dims(np.abs(np.max(X, axis=1) - np.min(X, axis=1)),1)
        elif args.measure == 'MeanAD':
            X = np.expand_dims(np.mean(np.abs(X - np.expand_dims(np.mean(X, axis=1),axis=1)), axis=1),axis=1)
        elif args.measure == 'MADs':
            X = np.stack((scipy.stats.median_absolute_deviation(X, axis=1),
                                np.abs(np.max(X, axis=1) - np.min(X, axis=1)),
                                np.mean(np.abs(X - np.expand_dims(np.mean(X, axis=1),axis=1)), axis=1)),
                                axis=1)

    # kfold parameters
    n_repeats = args.outer_cv
    n_splits = 5
    # which classifiers
    classifiers = ['lr']
    # feature selection for non-sliding window
    topn_perc = 100
    # for null dist
    compute_nulldist = args.compute_nulldist
    null_tag = '_with_nulldist' if compute_nulldist else ''
    n_perms = 10000
    n_perms_use = n_perms if compute_nulldist else 1
    # output data
    fn = f'results/decoding_{args.dtype}{irf_tag}{alt_tag}_{args.measure}_{n_repeats}outer-cv{null_tag}.pkl'
    fn_matlab = fn.replace('.pkl', '.mat')

    print(f'working on {fn}')

    if os.path.exists(fn) and not args.overwrite:
        with open(fn, 'rb') as f:
            all_data = pickle.load(f)
    else:
        # for splitting the data, let's do 5-fold with 20 repeats
        rskf = RepeatedStratifiedKFold(n_splits=n_splits, n_repeats=n_repeats,
            random_state=1)

    ###
        full_accs = {}
        for classifier in classifiers:
            full_acc = []
            window_acc = []
            for train_inds, test_inds in rskf.split(X, Y):
                classif, manual_grid_search = get_classifier(classifier, select_topn_perc=topn_perc, n_jobs=args.n_jobs)
                if manual_grid_search:
                    classif = classif.best_estimator_
                classif = classif.fit(X[train_inds,:], Y[train_inds])
                result = classif.predict(X[test_inds,:])
                full_acc.append(np.mean(result == Y[test_inds]))
            full_accs[classifier] = np.mean(full_acc)

        if compute_nulldist:
            full_accs_null = {}
            for classifier in classifiers:
                full_accs_null[classifier] = []
                print(f'beginning classifier {classifier} null permutations...')
                for nullperm in tqdm(range(n_perms)):
                    full_acc = []
                    for train_inds, test_inds in rskf.split(X, Y):
                        classif, manual_grid_search = get_classifier(classifier, select_topn_perc=topn_perc, n_jobs=args.n_jobs)
                        if manual_grid_search:
                            classif = classif.best_estimator_
                        X_train, Y_train = X[train_inds,:], Y[train_inds]
                        X_test, Y_test = X[test_inds,:], Y[test_inds]
                        if compute_nulldist:
                            Y_train = np.random.permutation(Y_train)
                        classif = classif.fit(X_train, Y_train)
                        result = classif.predict(X_test)
                        full_acc.append(np.mean(result == Y_test))
                    full_accs_null[classifier].append(np.mean(full_acc))
                full_accs_null[classifier] = np.array(full_accs_null[classifier])

            all_data = dict(full_accs=full_accs, full_accs_null=full_accs_null)
        else:
            all_data = dict(full_accs=full_accs)
        with open(fn, 'wb') as f:
            pickle.dump(all_data, f)

        savemat(fn_matlab, all_data)
