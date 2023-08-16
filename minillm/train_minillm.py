import torch
import os
import json
import torch.distributed as dist
from accelerate import init_empty_weights

from transformers import (
    AutoModelForCausalLM,
    AutoConfig,
    ParallelOPTForCausalLM,
    ParallelGPTJForCausalLM,
    ParallelGPT2LMHeadModel,
    ParallelLlamaForCausalLM)

parallel_model_map = {
    "opt": ParallelOPTForCausalLM,
    "gpt2": ParallelGPT2LMHeadModel,
    "gptj": ParallelGPTJForCausalLM,
    "llama": ParallelLlamaForCausalLM
}

from arguments import get_args
from utils import print_args, initialize, load_parallel, get_tokenizer

from minillm import train, Reward


def get_teacher_model(args, device):
    config = AutoConfig.from_pretrained(args.teacher_model_path)
    if args.model_parallel:
        config.is_model_parallel = True
        with init_empty_weights():
            model = parallel_model_map[args.model_type](config).half()
        load_parallel(model, args.teacher_model_path)
        model = model.to(device)
    else:
        config.is_model_parallel = False
        model = AutoModelForCausalLM.from_pretrained(args.teacher_model_path, config=config, device_map={"": device}, torch_dtype=torch.float16)
    
    model.eval()

    return model


def main():
    
    args = get_args()
    initialize(args)

    device = torch.cuda.current_device()
    
    os.makedirs(args.save, exist_ok=True)
    if dist.get_rank() == 0:
        print_args(args)
        with open(os.path.join(args.save, "args.json"), "w") as f:
            json.dump(vars(args), f)
            
    with open(args.deepspeed_config, "r") as f:
        ds_config = json.load(f)

    ds_config["gradient_accumulation_steps"] = args.gradient_accumulation_steps
    ds_config["train_micro_batch_size_per_gpu"] = args.batch_size
    ds_config["gradient_clipping"] = args.clip_grad
    ds_config["steps_per_print"] = 10000000
    
    args.deepspeed_config = None
    
    if args.teacher_model_type is None:
        args.teacher_model_type = args.model_type
    
    teacher_model = get_teacher_model(args, device)
    tokenizer = get_tokenizer(args)
    
    reward = Reward(args, tokenizer, teacher_model)
    
    train(
        args=args,
        tokenizer=tokenizer,
        reward_fn=reward.reward_fn,
        teacher_model=teacher_model,
        ds_config=ds_config,
        prompt_data=args.prompt_data_dir,
        eval_prompt_data=args.prompt_data_dir,
        lm_data=args.lm_data_dir,
        eval_lm_data=args.lm_data_dir,
    )


if __name__ == "__main__":
    main()