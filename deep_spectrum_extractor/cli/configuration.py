import argparse
import configparser
import csv
from itertools import chain
from os import listdir, makedirs
from os.path import join, isfile, basename, expanduser, dirname, isdir


class Configuration:
    """
    This class handles the configuration of the deep spectrum extractor by reading commandline options and the
    configuration file. It then parses the labels for the audio files and configures the Caffe Network used for
    extraction.
    """

    def __init__(self):
        # set default values
        self.model_directory = join(expanduser('~'), 'caffe-master/models/bvlc_alexnet')
        self.model_def = ''
        self.model_weights = ''
        self.gpu_mode = True
        self.device_ids = [0]
        self.number_of_processes = None
        self.folders = []
        self.output = ''
        self.cmap = 'viridis'
        self.label_file = None
        self.labels = None
        self.label_dict = {}
        self.layer = 'fc7'
        self.chunksize = None
        self.step = None
        self.nfft = 256
        self.y_limit = None
        self.reduced = None
        self.size = 227
        self.files = []
        self.output_spectrograms = None
        self.net = None
        self.transformer = None
        self.parser = None
        self.net = None
        self.config = None

    def parse_arguments(self):
        """
        Creates a commandline parser and handles the given options.
        :return: Nothing
        """
        self.parser = argparse.ArgumentParser(description='Extract deep spectrum features from wav files',
                                              formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        required_named = self.parser.add_argument_group('Required named arguments')
        required_named.add_argument('-f', nargs='+', help='folder(s) where your wavs reside', required=True)
        required_named.add_argument('-o',
                                    help='the file which the features are written to. Supports csv and arff formats',
                                    required=True)
        self.parser.add_argument('-lf',
                                 help='csv file with the labels for the wavs in the form: \'test_001.wav, label\'. If nothing is specified here or under -labels, the name(s) of the directory/directories are used as labels.',
                                 default=None)
        self.parser.add_argument('-labels', nargs='+',
                                 help='define labels for folders explicitly in format: labelForFirstFolder labelForSecondFolder ...',
                                 default=None)
        self.parser.add_argument('-cmap', default='viridis',
                                 help='define the matplotlib colour map to use for the spectrograms')
        self.parser.add_argument('-config',
                                 help='path to configuration file which specifies caffe model and weight files. If this file does not exist a new one is created and filled with the standard settings-',
                                 default='deep.conf')
        self.parser.add_argument('-layer', default='fc7',
                                 help='name of CNN layer (as defined in caffe prototxt) from which to extract the features.')
        # self.parser.add_argument('-chunksize', default=None, type=int,
        #                         help='define a chunksize in ms. wav data is split into chunks of this length before feature extraction.')
        # self.parser.add_argument('-step', default=None, type=int,
        #                         help='stepsize for creating the wav segments in ms. Defaults to the size of the chunks if -chunksize is given but -step is omitted.')
        self.parser.add_argument('-t',
                                 help='Extract deep spectrum features from windows with specified length and hopsize in seconds.',
                                 nargs=2, type=float, default=[None, None])
        self.parser.add_argument('-nfft', default=256,
                                 help='specify the size for the FFT window in number of samples', type=int)
        self.parser.add_argument('-reduced', nargs='?',
                                 help='a reduced version of the feature set is written to the given location.',
                                 default=None, const='deep_spectrum_reduced.arff')
        self.parser.add_argument('-np', type=int,
                                 help='define the number of processes used in parallel for the extraction. If None defaults to cpu-count',
                                 default=None)
        self.parser.add_argument('-ylim', type=int,
                                 help='define a limit for the y-axis for plotting the spectrograms',
                                 default=None)

        self.parser.add_argument('-specout',
                                 help='define an existing folder where spectrogram plots should be saved during feature extraction. By default, spectrograms are not saved on disk to speed up extraction.',
                                 default=None)
        self.parser.add_argument('-net',
                                 help='specify the CNN that will be used for the feature extraction. This should be a key for which a model directory is assigned in the config file.',
                                 default='alexnet')

        args = vars(self.parser.parse_args())
        self.folders = args['f']
        self.cmap = args['cmap']
        self.output = args['o']
        makedirs(dirname(self.output), exist_ok=True)
        self.label_file = args['lf']
        self.labels = args['labels']
        self.layer = args['layer']
        self.number_of_processes = args['np']

        # if either chunksize or step are not given they default to the value of the other given parameter
        # self.chunksize = args['chunksize'] if args['chunksize'] else args['step']
        # self.step = args['step'] if args['step'] else self.chunksize

        self.chunksize = args['t'][0]
        self.step = args['t'][1]
        self.nfft = args['nfft']
        self.reduced = args['reduced']
        self.output_spectrograms = args['specout']
        self.y_limit = args['ylim']
        self.net = args['net']
        self.config = args['config']

        # list all .wavs for the extraction found in the given folders
        self.files = list(chain.from_iterable([self._find_wav_files(folder) for folder in self.folders]))
        if not self.files:
            self.parser.error('No .wavs were found. Check the specified input paths.')

        if self.output_spectrograms:
            makedirs(self.output_spectrograms, exist_ok=True)

        if self.labels is not None and len(self.folders) != len(self.labels):
            self.parser.error(
                'Labels have to be specified for each folder: ' + str(len(self.folders)) + ' expected, ' + str(
                    len(self.labels)) + ' received.')
        print('Parsing labels...')
        if self.label_file is None:
            self._create_labels_from_folder_structure()
        else:
            self._read_label_file()

        self._load_config()
        self._configure_caffe()

    @staticmethod
    def _find_wav_files(folder):
        if listdir(folder):
            wavs = [join(folder, wav_file) for wav_file in listdir(folder) if
                    isfile(join(folder, wav_file)) and (wav_file.endswith('.wav') or wav_file.endswith('.WAV'))]
            return wavs + list(chain.from_iterable(
                [Configuration._find_wav_files(join(folder, subfolder)) for subfolder in listdir(folder) if
                 isdir(join(folder, subfolder))]))
        else:
            return []

    def _read_label_file(self):
        """
        Read labels from either .csv or .tsv files
        :param parser: commandline parser
        :return: Nothing
        """

        # delimiters are decided by the extension of the labels file
        if self.label_file.endswith('.tsv'):
            reader = csv.reader(open(self.label_file, newline=''), delimiter="\t")
        else:
            reader = csv.reader(open(self.label_file, newline=''))
        header = next(reader)
        classes = header[1:]

        self.label_dict = {}

        # a list of distinct labels is needed for deciding on the nominal class values for .arff files
        self.labels = [(class_name, set([])) for class_name in classes]

        # parse the label file line by line
        for row in reader:
            key = row[0]
            self.label_dict[key] = row[1:]
            for i, label in enumerate(row[1:]):
                if self._is_number(label):
                    self.labels[i] = (self.labels[i][0], None)
                else:
                    self.labels[i][1].add(label)
        file_names = set(map(basename, self.files))

        # check if labels are missing for specific files
        missing_labels = file_names.difference(self.label_dict)
        if missing_labels:
            self.parser.error('No labels for: ' + ', '.join(missing_labels))

    @staticmethod
    def _is_number(s):
        try:
            complex(s)  # for int, long, float and complex
        except ValueError:
            return False

        return True

    def _create_labels_from_folder_structure(self):
        """
        If no label file is given, either explicit labels or the folder structure is used as class values for the input.
        :return: Nothing
        """
        if self.labels is None:
            self.label_dict = {basename(wav): [basename(dirname(wav))] for wav in self.files}
        else:
            # map the labels given on the commandline to all files in a given folder in the order both appear in the
            # parsed options.
            self.label_dict = {basename(wav): [self.labels[folder_index]] for folder_index, folder in enumerate(self.folders) for
                               wav in
                               self._find_wav_files(folder)}
        labels = list(map(lambda x: x[0], self.label_dict.values()))
        print(labels)
        self.labels = [('class', set(labels))]

    def _load_config(self):
        """
        Parses the configuration file given on the commandline. If it does not exist yet, creates a new one containing
        standard settings.
        :param conf_file: configuration file to parse or create
        :return: Nothing
        """
        conf_parser = configparser.ConfigParser()

        # check if the file exists and parse it
        if isfile(self.config):
            print('Found config file ' + self.config)
            conf_parser.read(self.config)
            main_conf = conf_parser['main']
            self.gpu_mode = int(main_conf['gpu']) == 1
            self.device_ids = list(map(int, main_conf['device_ids'].split(',')))
            self.size = int(main_conf['size'])

            net_conf = conf_parser['nets']
            if self.net in net_conf:
                self.model_directory = net_conf[self.net]
            else:
                self.parser.error('No model directory defined for {} in {}'.format(self.net, self.config))


        # if not, create it with standard settings
        else:
            print('Writing standard config to ' + self.config)
            main_conf = {'gpu': '1' if self.gpu_mode else '0',
                         'device_ids': str(','.join(map(str, self.device_ids))),
                         'size': str(self.size)}
            net_conf = {'alexnet': self.model_directory}
            conf_parser['main'] = main_conf
            conf_parser['nets'] = net_conf
            with open(self.config, 'w') as configfile:
                conf_parser.write(configfile)

    def _configure_caffe(self):
        """
        Sets up the pre-trained CNN used for extraction.
        :param parser: commandline parser object used in the set up
        :return: Nothing
        """
        directory = self.model_directory

        if not isdir(self.model_directory):
            self.parser.error(
                'Directory {} specified in {} for net {} does not exist!'.format(self.model_directory, self.config,
                                                                                 self.net))
        # load model definition
        model_defs = [join(directory, file) for file in listdir(directory) if file.endswith('deploy.prototxt')]
        if model_defs:
            self.model_def = model_defs[0]
            print('CaffeNet definition: ' + self.model_def)
        else:
            self.model_def = ''
            self.parser.error('No model definition found in ' + directory + '.')

        # load model wights
        possible_weights = [join(directory, file) for file in listdir(directory)
                            if file.endswith('.caffemodel')]
        if possible_weights:
            self.model_weights = possible_weights[0]
            print('CaffeNet weights: ' + self.model_weights)
        else:
            self.parser.error('No model weights found in ' + directory + '.')

            # # set mode to GPU or CPU computation
            # if self.gpu_mode:
            #     caffe.set_device(int(self.device_id))
            #     caffe.set_mode_gpu()
            #     print('Using GPU device ' + str(self.device_id))
            # else:
            #     print('Using CPU-Mode')
            #     caffe.set_mode_cpu()
            #
            # print('Loading Net')
            # self.net = caffe.Net(model_def, caffe.TEST, weights=model_weights)
            # self.transformer = caffe.io.Transformer({'data': self.net.blobs['data'].data.shape})
            # self.transformer.set_transpose('data', (2, 0, 1))
            # self.transformer.set_raw_scale('data', 255)  # rescale from [0, 1] to [0, 255]
            # self.transformer.set_channel_swap('data', (2, 1, 0))  # swap channels from RGB to BGR
            #
            # # reshape input layer as batch processing is not needed
            # shape = self.net.blobs['data'].shape
            # self.net.blobs['data'].reshape(1, shape[1], shape[2], shape[3])
            # self.net.reshape()
