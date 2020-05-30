This miniwdl plugin implements a few customizations for the IDseq SFN-WDL backend which don't quite warrant dedicated packages:

* Parsing JSON log messages from tasks and forwarding them in structured form
* Passing through environment variables from runner to tasks (supports ECR credential handling for idseq-dag)

These functions, and any new ones under consideration, should be used sparingly in order to minimize WDL portability impacts.
