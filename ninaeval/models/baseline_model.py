from ninaeval.models.model import ClassifierModel, FeatureExtractor
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from pywt import wavedec

#
# Baseline Classifiers
#
class RandomForest(ClassifierModel):

    num_trees = 128

    def __init__(self):
        self.classifier = RandomForestClassifier(n_estimators=self.num_trees)

    def train_model(self, train_features, train_labels):
        self.classifier.fit(train_features, train_labels)

    def perform_inference(self, test_features, test_labels):
        predictions = self.classifier.predict(test_features)
        return self.classifier_accuracy(predictions, test_labels)

#
# Baseline Feature Extractors
#
class RMS(FeatureExtractor):

    def extract_feature_point(self, raw_samples):
        return np.sqrt(np.mean(np.square(raw_samples), axis=0))

    def global_setup(self, all_raw_samples):
        pass

class TimeStatistics(FeatureExtractor):

    noise_thresh = 2

    # Note: We do not use "Mean Absolute Value Slope"
    def extract_feature_point(self, raw_samples):

        window_size     = raw_samples.shape[0]
        num_channels    = raw_samples.shape[1]

        mean_abs            = np.mean(np.abs(raw_samples), axis=0).astype(np.uint16)
        num_zeros           = np.zeros(num_channels, dtype=np.uint16)
        num_slope_changes   = np.zeros(num_channels, dtype=np.uint16)
        waveform_length     = np.zeros(num_channels, dtype=np.uint16)

        for i in range(num_channels):
            for j in range(window_size):

                # Check for zero crossings
                if (raw_samples[j][i] < self.noise_thresh) and (raw_samples[j][i] > -self.noise_thresh):
                    num_zeros[i] += 1

                # Check for slope changes
                if (j > 0) and (j < window_size - 1):
                    left    = raw_samples[j-1][i]
                    mid     = raw_samples[j][i]
                    right   = raw_samples[j+1][i]

                    condition_1 = (mid > left + self.noise_thresh) and (mid > right + self.noise_thresh)
                    condition_2 = (mid + self.noise_thresh < left) and (mid + self.noise_thresh < right)

                    if condition_1 or condition_2:
                        num_slope_changes[i] += 1

                # Compute waveform length
                if j > 0:
                    left    = raw_samples[j - 1][i]
                    mid     = raw_samples[j][i]
                    waveform_length[i] += np.abs(mid - left)

        # Concat time statistics features
        time_stat_vec = np.concatenate((mean_abs, num_zeros, num_slope_changes, waveform_length))
        return time_stat_vec

    def global_setup(self, all_raw_samples):
        pass


class HistogramBins(FeatureExtractor):

    num_bins    = 20    # Assumed to be a multiple of 2
    threshold   = 3.0   # Number of standard deviations

    # Filled via global_setup()
    channel_mean    = None
    channel_stddev  = None

    def extract_feature_point(self, raw_samples):

        num_channels = raw_samples.shape[1]

        # Histogram range
        min_val = self.channel_mean - self.threshold * self.channel_stddev
        max_val = self.channel_mean + self.threshold * self.channel_stddev

        bins        = np.zeros(shape=(num_channels, self.num_bins), dtype=np.float32)
        cen_samples = raw_samples - self.channel_mean

        for i in range(num_channels):
            bins[i, :] = np.histogram(cen_samples[:, i], bins=self.num_bins, range=(min_val[i], max_val[i]))[0]

        # Manually compute histogram (Commented out, slower, yet slightly better performance)
        #
        #
        # window_size   = raw_samples.shape[0]
        # bins          = np.zeros(shape=(self.num_bins, num_channels), dtype=np.uint8)
        #
        # clip_samples    = np.clip(raw_samples, min_val, max_val)
        # cen_samples     = clip_samples - self.channel_mean
        #
        # bin_size    = 2.0 * self.threshold * self.channel_stddev / float(self.num_bins)
        # bins_alloc  = (cen_samples / bin_size) + self.num_bins/ 2.0 - 0.5
        # bins_alloc  = bins_alloc.astype(np.uint8)
        #
        # #
        # # Increment the bins
        # #
        # for channel in range(num_channels):
        #     for i in range(window_size):
        #         bins[bins_alloc[i][channel]][channel] += 1
        # bins = bins / float(window_size)

        bins = np.reshape(bins, (num_channels * self.num_bins))
        return bins


    def global_setup(self, all_raw_samples):

        num_windows     = all_raw_samples.shape[0]
        window_size     = all_raw_samples.shape[1]

        #
        # Compute mean and variance
        #
        window_mean         = np.mean(all_raw_samples, axis=0)
        channel_mean        = np.mean(window_mean, axis=0)
        self.channel_mean   = channel_mean

        window_sq_dev_sum   = np.sum(np.square(all_raw_samples - self.channel_mean), axis=0)
        channel_variance    = np.sum(window_sq_dev_sum, axis=0) / (float(num_windows * window_size - 1))
        channel_stddev      = np.sqrt(channel_variance)
        self.channel_stddev = channel_stddev


class MarginalDiscreteWaveletTransform(FeatureExtractor):

    num_levels      = 3
    mother_wavelet  = "db7"

    def extract_feature_point(self, raw_samples):

        num_channels    = raw_samples.shape[1]
        all_coeff       = []

        for i in range(num_channels):
            coeffs = wavedec(raw_samples[:, i], self.mother_wavelet, level=self.num_levels)

            # "Marginal" of each level
            for j in range(self.num_levels):
                all_coeff.append(np.sum(np.abs(coeffs[j])))

        all_coeff   = np.array(all_coeff)
        return all_coeff

    def global_setup(self, all_raw_samples):
        pass


class AllFeatures(FeatureExtractor):

    def __init__(self):
        self.ts     = TimeStatistics()
        self.rms    = RMS()
        self.hist   = HistogramBins()
        self.mdwt   = MarginalDiscreteWaveletTransform()

    def extract_feature_point(self, raw_samples):

        ts_feat     = self.ts.extract_feature_point(raw_samples)
        rms_feat    = self.rms.extract_feature_point(raw_samples)
        hist_feat   = self.hist.extract_feature_point(raw_samples)
        mdwt_feat   = self.mdwt.extract_feature_point(raw_samples)

        return np.concatenate((ts_feat, rms_feat, hist_feat, mdwt_feat))

    def global_setup(self, all_raw_samples):
        self.hist.global_setup(all_raw_samples)