#coding: utf-8
# v1.2 也可以先只取出每个句子，在batch_iter阶段转为id
# 这样好处是不需要一开始就将整个数据集进行转换，减小等待时间，减少内存消耗；
# 坏处是对每个句子每个epoch都要转换一遍，增加了整体的运行时间；

import tensorflow as tf
import numpy as np
import os 
import sys
import json 
import random
import time

from current_model import Config
from current_model import Model

os.environ['CUDA_VISIBLE_DEVICES'] = str(3-Config.gpu_id)
vocab = {}

def get_word_and_char(sentence):
    words = sentence.split()
    word_ids = [vocab[w] for w in words]
    digitize_char = lambda x : ord(x) if 0<ord(x)<256 else 1            # 只有padding的才是0，非padding部分都大于0
    char_ids = [[digitize_char(c) for c in w] for w in words]
    return word_ids, char_ids

def digitize_data(fname):
    tasks = []
    start_time = time.time()
    with open(Config.dataset + '/' + fname + '.txt') as fi:
        for line in fi:
            label, p_string, q_string = line.strip().split('\t')
            p_word, p_char = get_word_and_char(p_string)
            q_word, q_char = get_word_and_char(q_string)
            if not(Config.dataset == 'semeval2017' and fname != 'train'):
                label = Config.label_list.index(label)
            tasks.append([p_word, p_char, q_word, q_char, label])
    print('loading {}:\tsize:{}\ttime:{}'.format(fname, len(tasks), time.time()-start_time))
    return tasks


# padding成固定shape,(b,m) (b,m,w),虽然各batch的b,m,w可能不同,
def batch_iter(data, batch_size, shuffle, is_train):
    num_batchs_per_epoch = int((len(data)-1)/batch_size) + 1
    num_epochs = 500 if is_train else 1
    for epoch in range(num_epochs):
        if shuffle:
            random.shuffle(data)
        for batch_num in range(num_batchs_per_epoch):
            start_index = batch_num * batch_size
            end_index = min((batch_num+1)*batch_size, len(data))
            batch_data = data[start_index:end_index]
            p_words, p_chars, q_words, q_chars, label = list(zip(*batch_data))
            p_words, p_chars = pad_word_and_char(p_words, p_chars)
            q_words, q_chars = pad_word_and_char(q_words, q_chars)
            yield [p_words, q_words, p_chars, q_chars, np.array(label)]
            
def pad_word_and_char(words, chars):
    max_sent = min(len(max(words, key=len)), Config.max_sent)
    pad_sent = lambda x: x[:max_sent] if len(x)>max_sent else x+[0]*(max_sent-len(x))
    padded_sent = [pad_sent(sent) for sent in words]

    flatten_chars = [j for i in chars for j in i]
    max_word = min(len(max(flatten_chars, key=len)), Config.max_word)
    pad_word = lambda x: x[:max_sent] if len(x)>max_sent else x+[[0]]*(max_sent-len(x))
    pad_char = lambda x: x[:max_word] if len(x)>max_word else x+[0]*(max_word-len(x))
    padded_word = [[pad_char(word) for word in pad_word(sent)] for sent in chars]
    return np.array(padded_sent), np.array(padded_word)

if __name__ == '__main__':

    embedding = []
    start_time = time.time()
    with open(Config.dataset + '/embedding.txt') as fe:
        for i, line in enumerate(fe):
            items = line.split()
            vocab[items[0]]= i
            embedding.append(list(map(float,items[1:])))
    print('loading embed:\twords:{}\ttime:{}'.format(len(embedding), time.time()-start_time))

    train_data = digitize_data('train')        
    dev_data = digitize_data('dev')
    test_data = digitize_data('test')        

    model = Model(np.array(embedding))
    tf_config = tf.ConfigProto()
    tf_config.gpu_options.allow_growth = True

    with tf.Session(config = tf_config) as sess:
        model.build_model()
        for v in tf.trainable_variables():
            print('name:{}\tshape:{}'.format(v.name,v.shape))
        tf.set_random_seed(1123)
        tf.global_variables_initializer().run()
        saver = tf.train.Saver()
        if Config.restore and len([v for v in os.listdir('weights/') if '.index' in v]):
            saver.restore(sess, tf.train.latest_checkpoint('weights/'))
        batch_trains = batch_iter(train_data,Config.batch_size,True,True)
        losses = []
        show_time = time.time()
        best_dev_acc = 0
        total_steps = len(train_data)/Config.batch_size
        
        def get_result(data, type='dev'):
            batchs = batch_iter(data, Config.batch_size, False, False)
            predict = '' if Config.dataset == 'semeval2017' else 0
            for batch in batchs:
                predict += model.test_batch(sess, batch)
            if Config.dataset == 'semeval2017':
                with open('scorer/predict_'+type, 'w') as fw:
                    fw.write(predict)
                result = os.popen('python2 scorer/ev.py scorer/gold_{} scorer/predict_{}'.format(type,type)).readlines()[1].strip()[-6:]
            return float(result) if Config.dataset=='semeval2017' else predict/len(data)


        for step,batch_train in enumerate(batch_trains):
            batch_loss = model.train_batch(sess, batch_train)
            sys.stdout.write("\repoch:{:.5f}\t\t\tloss:{}".format(step/total_steps, batch_loss))
            losses.append(batch_loss)
            display_step = int(total_steps/3) if step<6*total_steps else int(total_steps/6)
            if step % display_step ==0:
                sys.stdout.write('\repoch:{:.5f}\t\taverage_loss:{}\n'.format(step/total_steps, sum(losses)/len(losses)))
                losses = []
                dev_acc, test_acc = get_result(dev_data, 'dev'), get_result(test_data, 'test')
                print('dev_acc:{}\t\ttest_acc:{}\t\tshow_time:{}'.format(dev_acc, test_acc, time.time()-show_time))
                if (dev_acc > best_dev_acc) and (step > 3*total_steps):
                    best_dev_acc = dev_acc
                    saver.save(sess, 'weights/best', step)
                show_time = time.time()

