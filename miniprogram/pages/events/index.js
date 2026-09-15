const api=require('../../utils/api');const {formatDate,defaultDeadline}=require('../../utils/date')
Page({
 data:{tab:'lottery',events:[],loading:true,showForm:false,form:{title:'',description:'',deadline:defaultDeadline(),limit:'',allowNote:false}},
 onLoad(q){this.setData({tab:q.type||'lottery'});this.load()},onPullDownRefresh(){this.load().finally(()=>wx.stopPullDownRefresh())},
 load(){return api.call('events.list',{type:this.data.tab},{loading:false,silent:true}).then(events=>this.setData({events:events.map(e=>({...e,deadlineText:formatDate(e.deadline,true)})),loading:false})).catch(()=>this.setData({loading:false,events:[]}))},
 changeTab(e){this.setData({tab:e.currentTarget.dataset.tab,showForm:false,loading:true});this.load()},toggleForm(){this.setData({showForm:!this.data.showForm})},
 input(e){this.setData({[`form.${e.currentTarget.dataset.key}`]:e.detail.value})},switchNote(e){this.setData({'form.allowNote':e.detail.value})},changeDate(e){this.setData({'form.deadline':`${e.detail.value} 20:00`})},
 create(){const f=this.data.form;if(!f.title.trim())return wx.showToast({title:'请填写标题',icon:'none'});api.call('events.create',{type:this.data.tab,...f,limit:Number(f.limit)||0},{title:'正在发起'}).then(()=>{wx.showToast({title:'发起成功'});this.setData({showForm:false,form:{title:'',description:'',deadline:defaultDeadline(),limit:'',allowNote:false}});this.load()}).catch(()=>{})},
 join(e){api.call('events.join',{eventId:e.currentTarget.dataset.id},{title:'报名中'}).then(()=>{wx.showToast({title:'参与成功'});this.load()}).catch(()=>{})},
 draw(e){api.call('events.draw',{eventId:e.currentTarget.dataset.id},{title:'开奖中'}).then(d=>{wx.showModal({title:'开奖结果',content:d.winnerName?`恭喜 ${d.winnerName}`:'暂无参与者',showCancel:false});this.load()}).catch(()=>{})}
})
