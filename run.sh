#!/bin/bash
# this script is for debugging and quick runs
# dir=/home/statler/lcharlin/arxiv/dat/dataset_toy/
out_dir=/home/waldorf/altosaar/projects/arxiv/fit/ctpf-debug/

dir=/home/statler/lcharlin/arxiv/dat/dataset_2003-2012_clean/
# out_dir=/home/waldorf/altosaar/projects/arxiv/fit/hpmf-categorywise/
# out_dir=/home/waldorf/altosaar/projects/arxiv/fit/ctpf-stagewise-heldout/

python job_handler.py \
  --train_file=${dir}train.tsv \
  --validation_file=${dir}validation.tsv \
  --test_file=${dir}test.tsv \
  --item_info_file=${dir}items_arxiv_info.tsv \
  --user_info_file=${dir}users.tsv \
  --out_dir=${out_dir} \
  --binarize_true \
  --model=pmf \
  --fit_opt=alternating_updates \
  --min_iterations=10 \
  --seed=5532 \
  --observed_topics_true \
  --stdout \
