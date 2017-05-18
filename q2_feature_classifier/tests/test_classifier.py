# ----------------------------------------------------------------------------
# Copyright (c) 2016-2017, QIIME 2 development team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file LICENSE, distributed with this software.
# ----------------------------------------------------------------------------

import json
import os

from qiime2.sdk import Artifact
from q2_types.feature_data import DNAIterator
from qiime2.plugins import feature_classifier
import pandas as pd
import skbio

from q2_feature_classifier._skl import _specific_fitters
from q2_feature_classifier.classifier import spec_from_pipeline, \
    pipeline_from_spec

from . import FeatureClassifierTestPluginBase


class ClassifierTests(FeatureClassifierTestPluginBase):
    package = 'q2_feature_classifier.tests'

    def setUp(self):
        super().setUp()
        self.taxonomy = Artifact.import_data(
            'FeatureData[Taxonomy]', self.get_data_path('taxonomy.tsv'))

        seq_path = self.get_data_path('se-dna-sequences.fasta')
        reads = Artifact.import_data('FeatureData[Sequence]', seq_path)
        fitter_name = _specific_fitters[0][0]
        fitter = getattr(feature_classifier.methods,
                         'fit_classifier_' + fitter_name)
        self.classifier = fitter(reads, self.taxonomy).classifier

    def test_fit_classifier(self):
        # fit_classifier should generate a working taxonomic_classifier
        reads = Artifact.import_data(
            'FeatureData[Sequence]',
            self.get_data_path('se-dna-sequences.fasta'))

        classify = feature_classifier.methods.classify_sklearn
        result = classify(reads, self.classifier)

        ref = self.taxonomy.view(pd.Series).to_dict()
        classified = result.classification.view(pd.Series).to_dict()

        right = 0.
        for taxon in classified:
            right += ref[taxon].startswith(classified[taxon])
        self.assertGreater(right/len(classified), 0.95)

    def test_fit_specific_classifiers(self):
        # specific and general classifiers should produce the same results
        gen_fitter = feature_classifier.methods.fit_classifier_sklearn
        classify = feature_classifier.methods.classify_sklearn
        reads = Artifact.import_data(
            'FeatureData[Sequence]',
            self.get_data_path('se-dna-sequences.fasta'))

        for name, spec in _specific_fitters:
            classifier_spec = json.dumps(spec)
            result = gen_fitter(reads, self.taxonomy, classifier_spec)
            result = classify(reads, result.classifier)
            gc = result.classification.view(pd.Series).to_dict()
            spec_fitter = getattr(feature_classifier.methods,
                                  'fit_classifier_' + name)
            result = spec_fitter(reads, self.taxonomy)
            result = classify(reads, result.classifier)
            sc = result.classification.view(pd.Series).to_dict()
            for taxon in gc:
                self.assertEqual(gc[taxon], sc[taxon])

    def test_pipeline_serialisation(self):
        # pipeline inflation and deflation should be inverse operations
        for name, spec in _specific_fitters:
            pipeline = pipeline_from_spec(spec)
            spec_one = spec_from_pipeline(pipeline)
            pipeline = pipeline_from_spec(spec_one)
            spec_two = spec_from_pipeline(pipeline)
            self.assertEqual(spec_one, spec_two)

    def test_classify(self):
        # test read direction detection and parallel classification
        classify = feature_classifier.methods.classify_sklearn
        seq_path = self.get_data_path('se-dna-sequences.fasta')
        reads = Artifact.import_data('FeatureData[Sequence]', seq_path)
        raw_reads = skbio.io.read(
            seq_path, format='fasta', constructor=skbio.DNA)
        rev_path = os.path.join(self.temp_dir.name, 'rev-dna-sequences.fasta')
        skbio.io.write((s.reverse_complement() for s in raw_reads),
                       'fasta', rev_path)
        rev_reads = Artifact.import_data('FeatureData[Sequence]', rev_path)

        result = classify(reads, self.classifier)
        fc = result.classification.view(pd.Series).to_dict()
        result = classify(rev_reads, self.classifier)
        rc = result.classification.view(pd.Series).to_dict()

        for taxon in fc:
            self.assertEqual(fc[taxon], rc[taxon])

        result = classify(reads, self.classifier, read_orientation='same')
        fc = result.classification.view(pd.Series).to_dict()
        result = classify(rev_reads, self.classifier,
                          read_orientation='reverse-complement')
        rc = result.classification.view(pd.Series).to_dict()

        for taxon in fc:
            self.assertEqual(fc[taxon], rc[taxon])

        result = classify(reads, self.classifier, chunk_size=100, n_jobs=2)
        cc = result.classification.view(pd.Series).to_dict()

        for taxon in fc:
            self.assertEqual(fc[taxon], cc[taxon])

    def test_unassigned_taxa(self):
        # classifications that don't meet the threshold should be "Unassigned"
        classify = feature_classifier.methods.classify_sklearn
        seq_path = self.get_data_path('se-dna-sequences.fasta')
        reads = Artifact.import_data('FeatureData[Sequence]', seq_path)
        result = classify(reads, self.classifier, confidence=1.)

        ref = self.taxonomy.view(pd.Series).to_dict()
        classified = result.classification.view(pd.Series).to_dict()

        assert 'Unassigned' in classified.values()
        for seq in reads.view(DNAIterator):
            id_ = seq.metadata['id']
            assert ref[id_].startswith(classified[id_]) or \
                classified[id_] == 'Unassigned'
