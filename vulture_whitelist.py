# vulture_whitelist.py
# Suppress false positives from the OP_TABLE dispatch pattern.

# -- private handlers (referenced only in OP_TABLE dict literal) -----------
_ = _list_tickets
_ = _get_ticket
_ = _board_cards
_ = _history
_ = _merge_status
_ = _description
_ = _create_ticket
_ = _add_comment
_ = _transition
_ = _approve
_ = _mark_done
_ = _merge_now
_ = _resume_blocked
_ = _migrate
_ = _set_priority

# -- Pydantic args models (used only via .model_validate() in handlers) -----
_ = ListTicketsArgs
_ = GetTicketArgs
_ = BoardCardsArgs
_ = HistoryArgs
_ = MergeStatusArgs
_ = DescriptionArgs
_ = CreateTicketArgs
_ = AddCommentArgs
_ = TransitionArgs
_ = ApproveArgs
_ = MarkDoneArgs
_ = MergeNowArgs
_ = ResumeBlockedArgs
_ = MigrateArgs
_ = SetPriorityArgs

# -- brokered.py: public API consumed by mill, not within board-agent ------
_ = BrokeredBoardResponder

# -- board_manager.py: public API consumed by mill + the CLI ---------------
_ = BoardManager
