import argparse
import csv
import numpy as np
import logging
import deepspectrum.tools.custom_arff as arff
from os.path import splitext, abspath, dirname
from os import makedirs

DESCRIPTION_REDUCE = 'Reduce a list of feature files by removing zero features.'

log = logging.getLogger(__name__)


def _reduce(file_name):
    with open(file_name, newline='') as file:
        if file_name.endswith('.arff'):
            reader = arff.ArffReader(file)
        else:
            reader = csv.reader(file, delimiter=',')
            next(reader)
        first_row = np.array(next(reader))
        indices_to_remove = set(
            np.where((first_row == '0.0') | (first_row == '0'))[0])
        for line in reader:
            data = np.array(line)
            indices_to_remove = indices_to_remove.intersection(
                np.where((data == '0.0') | (data == '0'))[0])
    return indices_to_remove


def _apply_reduction(input, output, indices_to_remove):

    with open(input,
              newline='') as input_file, open(output, 'w',
                                              newline='') as output_file:
        input_arff = input.endswith('.arff')
        output_arff = output.endswith('.arff')
        if input_arff:
            reader = arff.ArffReader(input_file)
            reduced_attributes = [
                reader.attributes[x] for x in range(len(reader.attributes))
                if x not in indices_to_remove
            ]
            if output_arff:
                writer = arff.ArffWriter(output_file,
                                         'Reduced ' + reader.relation,
                                         reduced_attributes)
            else:
                writer = csv.writer(output_file, delimiter=',')
                writer.writerow(
                    [attribute[0] for attribute in reduced_attributes])

        else:
            reader = csv.reader(input_file, delimiter=',')
            attributes = next(reader)
            reduced_attributes = [
                attributes[x] for x in range(len(attributes))
                if x not in indices_to_remove
            ]
            if output_arff:
                arff_attributes = [(attribute_name, 'numeric')
                                   for attribute_name in reduced_attributes]
                arff_attributes[0][1] = 'string'
                arff_attributes[:-1][1] = 'nominal'
                writer = arff.ArffWriter(output_file, 'Reduced Features',
                                         arff_attributes)
            else:
                writer = csv.writer(output_file, delimiter=',')
                writer.writerow(reduced_attributes)

        for line in reader:
            reduced_line = [
                line[index] for index in range(len(line))
                if index not in indices_to_remove
            ]
            writer.writerow(reduced_line)


def reduce_file(input, output):
    makedirs(dirname(output), exist_ok=True)
    indices_to_remove = _reduce(input)
    _apply_reduction(input, output, indices_to_remove)


def main(args=None):
    parser = argparse.ArgumentParser(
        description=DESCRIPTION_REDUCE,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('input',
                        nargs='+',
                        help='The feature files to reduce.')
    args = vars(parser.parse_args())
    input_files = list(map(abspath, args['input']))
    print('Selecting features to remove from {}...'.format(input_files[0]))
    features_to_remove = _reduce(input_files[0])
    print('Removing {} features at the following indices: {}'.format(
        str(len(features_to_remove)),
        ','.join(list(map(str, sorted(features_to_remove))))))
    for input_file in input_files:
        output_file = splitext(input_file)[0] + '.reduced' + splitext(
            input_file)[1]
        print('Reducing {}...'.format(input_file))
        _apply_reduction(input_file, output_file, features_to_remove)


if __name__ == '__main__':
    main()