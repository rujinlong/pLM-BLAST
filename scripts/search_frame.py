#!/usr/bin/env python

import sys
import os
import argparse
# add one level up directory
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
print(os.path.dirname(__file__))
import torch
import pandas as pd
from tqdm import tqdm

from alntools.base import Extractor
from alntools.density import embedding_similarity
from alntools import gather_all_paths, search_paths
from alntools.postprocess import measure_aln_overlap_with_pdblist, filter_result_dataframe

parser = argparse.ArgumentParser(description =  
	"""
	All vs all search for a given dataframe
	""",
	formatter_class=argparse.RawDescriptionHelpFormatter
	)
parser.add_argument('-i', '-in', help='path to dataframe input file',
                    required=True, dest='infile', type=str)
parser.add_argument('-o', '-out', help='path to search results',
                    required=False, dest='outfile', type=str)

args = parser.parse_args()



# prequisitions
# how many records from dataframe should be processed in negative - uses all
limit_records = 20
# minimal length of alignment
MIN_SPAN_LEN = 20
# border indices step
BFACTOR = 2
# moving average window size
MA_WINDOW = 1
# standard deviation threshold applied when scoring alignment route
# the bigger value the more conservative algorithm is
SIGMA_FACTOR = 1
# measure alignment hits with available `pdb_list` column
# in this example `pdb_list` contain indices of the Rossmann core
MEASURE_ALIGNMENT_WITH_TEMP = True
RAW = True
VERBOSE = False
INPUTFILE = args.infile.replace('.p', '')
#PATH_DATAFRAME = f"{INPUTFILE}.p"
PATH_DATAFRAME = args.infile
PATH_EMBEDDINGS = f"{INPUTFILE}.emb.prottrans"
if args.outfile == '':
    PATH_RESULTS = f"{INPUTFILE}.results.csv"
else:
    PATH_RESULTS = args.outfile


def main():
    global PATH_DATAFRAME, PATH_EMBEDDINGS, limit_records
    if os.path.isabs(PATH_DATAFRAME):
        if not os.path.isfile(PATH_DATAFRAME):
            raise FileNotFoundError(f'input dataframe path is invalid: {PATH_DATAFRAME}')
        if not os.path.isfile(PATH_EMBEDDINGS):
            raise FileNotFoundError(f'input embedding path is invalid: {PATH_EMBEDDINGS}')
    else:
        PATH_DATAFRAME = os.path.join(os.getcwd(), PATH_DATAFRAME)
        PATH_EMBEDDINGS = os.path.join(os.getcwd(), PATH_EMBEDDINGS)

    rtbdf = pd.read_pickle(PATH_DATAFRAME)
    print(f'input frame records: {rtbdf.shape[0]}')
    rtbdf['idx'] = list(range(rtbdf.shape[0]))
    rtbdf['len_chain'] = rtbdf['seq_chain'].apply(len)
    if limit_records > 0:
        rtbdf = rtbdf.head(limit_records)
    else:
        limit_records = rtbdf.shape[0]
    num_records = rtbdf.shape[0]
    num_iterations = int(num_records*(num_records-1)/2)
    # load embeddings
    
    embeddings = torch.load(PATH_EMBEDDINGS)
    print(f'loaded {len(embeddings)} embeddings')

    module = Extractor()
    module.LIMIT_RECORDS = limit_records
    module.MIN_SPAN_LEN = MIN_SPAN_LEN
    module.WINDOW_SIZE = MA_WINDOW
    module.BFACTOR = BFACTOR
    module.SIGMA_FACTOR = SIGMA_FACTOR

    records_stack = list()
    with tqdm(total=num_iterations) as progress_bar:
        for query_idx, query_row in rtbdf.iterrows():
            if limit_records <= query_idx: break
            query_embedding = embeddings[query_idx]
            for target_idx, target_row in rtbdf.iterrows():
                if query_idx <= target_idx: break
                # TODO Wrap into function
                target_embedding = embeddings[target_idx]
                # generate similarity matrix
                results = module.embedding_to_span(query_embedding, target_embedding)
                # find unique alignments
                # if no alignment is found move to the next iteration
                ################################
                if results.shape[0] == 0:
                    continue
                results = filter_result_dataframe(results)
                if results.shape[0] == 0:
                    assert 'error records lost in filtration process'
                # core overlap factor
                # calculate alignemnt - core pdb_list cover
                if MEASURE_ALIGNMENT_WITH_TEMP:
                    for _, sample in results.iterrows():
                        record = measure_aln_overlap_with_pdblist(
                            seq1_true=query_row.pdb_list,
                            seq2_true=target_row.pdb_list,
                            alignment=sample.indices)
                        record = {
                            'query_pdbchain' : query_row.pdb_chain,
                            'target_pdbchain': target_row.pdb_chain,
                            'query_cof': query_row.simplified_cofactor,
                            'target_cof': target_row.simplified_cofactor,
                            'path_score': sample.score,
                            'len' : sample.len,
                            **record
                        }
                        records_stack.append(record)
                else:
                    for _, sample in results.iterrows():
                        record = {
                            'query_cof': query_row.simplified_cofactor,
                            'target_cof': target_row.simplified_cofactor,
                            'path_score': sample.score,
                            'len' : sample.len
                        }
                        records_stack.append(record)
                progress_bar.update(1)
    
        if len(records_stack) == 0:
            if VERBOSE:
                print(f'no matches for {query_row.pdb_chain}  ({query_idx}) - {target_row.pdb_chain} ({target_idx})')
        results = pd.DataFrame(records_stack)
        results.to_csv(PATH_RESULTS)
    print('total matches: ', results.shape[0])


if __name__ == "__main__":
    main()