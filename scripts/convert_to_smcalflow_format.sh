python convert_to_smcalflow_format.py \
--original_smcal_train_file ../semantic_parsing_with_constrained_lm/data/benchclamp/raw/CalFlowV2/train.dataflow_dialogues.jsonl \
--original_smcal_valid_file ../semantic_parsing_with_constrained_lm/data/benchclamp/raw/CalFlowV2/valid.dataflow_dialogues.jsonl \
--find_event_train_file ../release_data/20230222-find_event.train.jsonl \
--find_event_valid_file ../release_data/20230222-find_event.subset.valid.jsonl \
--find_event_revise_train_file ../release_data/20230222-find_event_revise.train.proportional_split.jsonl \
--find_event_revise_valid_file ../release_data/20230222-find_event_revise.valid.proportional_split.jsonl \
--find_event_revise_edit_fragment_train_file ../release_data/20230222-find_event_revise.train.proportional_split.edit_fragment_plan.resplit.jsonl  \
--find_event_revise_edit_fragment_valid_file ../release_data/20230222-find_event_revise.valid.proportional_split.edit_fragment_plan.resplit.jsonl \
--find_event_revise_train_output ../semantic_parsing_with_constrained_lm/data/benchclamp/raw/CalFlowFindEventRevise/20230222-find_event_revise.train.proportional_split.smcalformat.jsonl \
--find_event_revise_valid_output ../semantic_parsing_with_constrained_lm/data/benchclamp/raw/CalFlowFindEventRevise/20230222-find_event_revise.valid.proportional_split.smcalformat.jsonl \
--find_event_revise_edit_fragment_train_output ../semantic_parsing_with_constrained_lm/data/benchclamp/raw/CalFlowFindEventReviseEditFragment/20230222-find_event_revise.train.proportional_split.edit_fragment_plan.resplit.smcalformat.jsonl \
--find_event_revise_edit_fragment_valid_output ../semantic_parsing_with_constrained_lm/data/benchclamp/raw/CalFlowFindEventReviseEditFragment/20230222-find_event_revise.valid.proportional_split.edit_fragment_plan.resplit.smcalformat.jsonl 